"""Recovery after power loss (Phase 6, spec §6 resilience rows).

Three invariants, one per failure mode a hard kill can cause:

1. **WAL atomicity** — a real process is killed mid-transaction. SQLite's WAL
   must roll the uncommitted transaction back on the next open, leave the
   committed prefix intact, and pass ``integrity_check``.
2. **Clip artifacts** — the clip encode writes straight to
   ``clips/{event_id}.mp4`` (no staging): a kill can strand a partial file.
   ``sweep_orphans`` reclaims it later without touching referenced media.
3. **Delivery durability** — a pending row with attempts/backoff survives the
   restart untouched and retries against the *pre-restart* counter (D4).

Test 1 runs its victim in a subprocess (``kill`` = TerminateProcess: no exit
hooks, no flush — the power-cut analog). The child writes five committed
events, then one more inside an open transaction and parks itself, so the
kill lands mid-write deterministically.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Camera, Event, Site
from app.db.session import create_engine_for
from app.services.alerts.delivery import DeliveryWorker
from app.services.events.retention import sweep_orphans

BACKEND_DIR = Path(__file__).resolve().parents[1]
BASE_TIME = datetime(2026, 10, 6, 12, 0)

# The victim process: five committed events, one mid-flight transaction, park.
# STDOUT "MIDFLIGHT" tells the parent the transaction's page image is in the
# WAL and it is now safe to kill.
_CHILD = textwrap.dedent(
    """
    import sys, time
    from datetime import datetime
    from app.db.base import Base
    from app.db.models import Camera, Event, Site
    from app.db.session import create_engine_for
    from sqlalchemy.orm import Session

    engine = create_engine_for(sys.argv[1])
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        site = Site(name="s", timezone="UTC")
        db.add(site)
        db.flush()
        camera = Camera(site_id=site.id, name="c", rtsp_url="rtsp://10.0.0.7/ch1")
        db.add(camera)
        db.flush()
        for i in range(5):
            db.add(
                Event(
                    site_id=site.id,
                    camera_id=camera.id,
                    rule_id=None,
                    triggered_by="system",
                    started_at=datetime(2026, 10, 6, 12, 0),
                    severity="warning",
                    summary=f"committed-{i}-" + "x" * 64,
                )
            )
        db.commit()
        db.add(
            Event(
                site_id=site.id,
                camera_id=camera.id,
                rule_id=None,
                triggered_by="system",
                started_at=datetime(2026, 10, 6, 12, 0),
                severity="warning",
                summary="midflight-" + "y" * 64,
            )
        )
        db.flush()
        print("MIDFLIGHT", flush=True)
        time.sleep(600)
    """
)


def _hard_kill_mid_write(db_path: Path) -> None:
    """Run the child, kill it hard once the mid-flight write is in the WAL."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_DIR)
    # CREATE_NO_WINDOW: a pytest run must not flash console windows; a
    # Windows-only flag — 0 is a no-op accepted on POSIX CI runners.
    flags = 0x0800_0000 if sys.platform == "win32" else 0
    child = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-c", _CHILD, str(db_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=str(BACKEND_DIR),
        creationflags=flags,
    )
    try:
        marker = child.stdout.readline()  # type: ignore[union-attr]
        assert marker.strip() == "MIDFLIGHT", (
            f"child never reached mid-flight (maybe crashed): {child.stderr.read()}"  # type: ignore[union-attr]
        )
        time.sleep(0.15)  # let the WAL record the in-flight page image
        child.kill()  # TerminateProcess: no flush, no exit hooks
        child.wait(timeout=10)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
        for stream in (child.stdout, child.stderr):
            if stream is not None:
                stream.close()


def test_power_kill_mid_write_leaves_wal_intact_and_uncommitted_work_invisible(
    tmp_path: Path,
) -> None:
    """Hard-kill a process mid-transaction; the next open converges (§6)."""
    db_path = tmp_path / "crash.db"
    _hard_kill_mid_write(db_path)

    engine = create_engine_for(db_path)  # the same connect path the engine uses
    try:
        with sessionmaker(bind=engine)() as db:
            assert db.execute(text("PRAGMA integrity_check")).scalar() == "ok"
            assert db.execute(text("PRAGMA foreign_key_check")).all() == []
            rows = db.execute(select(Event).order_by(Event.id)).scalars().all()
    finally:
        engine.dispose()

    assert len(rows) == 5, "the uncommitted mid-flight event must not exist"
    for i, row in enumerate(rows):
        assert row.summary.startswith(f"committed-{i}-"), "no torn rows"


def test_kill_artifact_clip_orphan_is_swept_and_nothing_else(
    db_session: Session, tmp_path: Path
) -> None:
    """A stranded partial clip (row lost in the kill) is reclaimed; kept media
    referenced by a committed row survives. At most one orphan, swept once."""
    (tmp_path / "clips").mkdir()
    artifact = tmp_path / "clips" / "901.mp4"
    artifact.write_bytes(b"\x00" * 512)  # truncated mp4: never finished the moov

    site = Site(name="s", timezone="UTC")
    db_session.add(site)
    db_session.flush()
    camera = Camera(site_id=site.id, name="c", rtsp_url="rtsp://10.0.0.7/ch1")
    db_session.add(camera)
    db_session.flush()
    survivor = tmp_path / "clips" / "900.mp4"
    survivor.write_bytes(b"v" * 64)
    db_session.add(
        Event(
            site_id=site.id,
            camera_id=camera.id,
            rule_id=None,
            triggered_by="system",
            started_at=BASE_TIME,
            severity="warning",
            summary="s",
            clip_path="clips/900.mp4",
        )
    )
    db_session.commit()

    stamp = BASE_TIME.timestamp()  # past the min age via `now`
    os.utime(artifact, (stamp, stamp))
    os.utime(survivor, (stamp, stamp))

    removed = sweep_orphans(db_session, media_root=tmp_path, min_age_s=0, now=BASE_TIME)
    assert removed == 1, "only the artifact goes; a referenced file never does"
    assert not artifact.exists()
    assert survivor.exists(), "committed rows keep their clips through the sweep"

    assert sweep_orphans(db_session, media_root=tmp_path, min_age_s=0, now=BASE_TIME) == 0, (
        "the sweep is done once the artifact is gone"
    )


def test_delivery_pending_survives_restart_preserving_backoff(
    tmp_path: Path,
) -> None:
    """Pending delivery rows survive the engine restart with their D4 counters."""
    db_path = tmp_path / "restart.db"

    # --- run #1: commit a pending event mid-backoff, then "die" (dispose) ---
    engine_a = create_engine_for(db_path)
    Base.metadata.create_all(engine_a)
    maker_a = sessionmaker(bind=engine_a)
    with maker_a() as db:
        site = Site(name="s", timezone="UTC")
        db.add(site)
        db.flush()
        camera = Camera(site_id=site.id, name="c", rtsp_url="rtsp://10.0.0.7/ch1")
        db.add(camera)
        db.flush()
        db.add(
            Event(
                site_id=site.id,
                camera_id=camera.id,
                rule_id=None,
                triggered_by="system",
                started_at=BASE_TIME,
                severity="critical",
                summary="person at dock",
                delivery_status="pending",
                delivery_attempts=2,
                last_attempt_at=BASE_TIME,  # backoff(2) = 20s from now
            )
        )
        db.commit()
    engine_a.dispose()  # the power cut

    # --- run #2: a fresh engine on the same file sees the row untouched ---
    engine_b = create_engine_for(db_path)
    maker_b = sessionmaker(bind=engine_b)
    try:
        with maker_b() as db:
            row = db.execute(select(Event)).scalars().one()
            assert row.delivery_status == "pending"
            assert row.delivery_attempts == 2, "D4: attempts are never reset"
            assert row.last_attempt_at == BASE_TIME

            class FakeNotifier:
                def __init__(self) -> None:
                    self.sent: list[int] = []

                async def send(self, event: Event) -> None:  # noqa: ANN001
                    self.sent.append(event.id)

            notifier = FakeNotifier()
            worker = DeliveryWorker(
                session_factory=maker_b,
                notifier_for=lambda _site_id: [notifier],
                now=lambda: BASE_TIME + timedelta(seconds=10),
            )

            # 10s < backoff(2)=20s: not due yet. The sweep must be a no-op
            # that does not bump the counter on mere observation.
            assert _sweep(worker) == 0
            db.expire_all()
            row = db.get(Event, row.id)
            assert row.delivery_attempts == 2, "backoff preserved across restart"
            assert row.delivery_status == "pending"

            # Past backoff: the same worker instance (now=+30s) delivers, and
            # the attempt counter continues from 2 — it does not restart at 0.
            worker._now = lambda: BASE_TIME + timedelta(seconds=30)  # noqa: SLF001
            assert _sweep(worker) == 1
            db.expire_all()
            row = db.get(Event, row.id)
            assert row.delivery_status == "sent"
            assert row.delivery_attempts == 3, "attempts continue, never reset"
    finally:
        engine_b.dispose()


def _sweep(worker: DeliveryWorker) -> int:
    """Bridge the async sweep_once into the sync test body."""
    import asyncio

    return asyncio.run(worker.sweep_once())
