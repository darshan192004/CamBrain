"""Settings defaults and environment overrides (spec §8.1, §2 trust boundary).

The bind default of 127.0.0.1 is a security control, not a convenience: the
box sits on a customer LAN and anyone on that LAN can reach the port. Binding
wider requires deliberate configuration, which is what CAMBRAIN_BIND_ALL is.
"""

from __future__ import annotations

from app.core.config import Settings


def test_defaults_bind_localhost() -> None:
    """Default bind is loopback-only (SECURITY §2: no trusted-LAN exemption)."""
    s = Settings(_env_file=None)
    assert s.bind_host == "127.0.0.1"
    assert s.bind_port == 8765
    assert s.bind_all is False


def test_access_and_refresh_ttls_match_spec() -> None:
    """Access 12h, refresh 7d (spec §8.4, API §5)."""
    s = Settings(_env_file=None)
    assert s.access_token_ttl_s == 43200
    assert s.refresh_token_ttl_s == 604800


def test_bind_all_env_enables_wide_bind(monkeypatch: object) -> None:
    """CAMBRAIN_BIND_ALL=1 flips the explicit opt-in (SECURITY §2)."""
    monkeypatch.setenv("CAMBRAIN_BIND_ALL", "1")  # type: ignore[attr-defined]
    s = Settings(_env_file=None)
    assert s.bind_all is True


def test_cors_allowlist_is_localhost_only() -> None:
    """No wildcard, ever — the allowlist is localhost origins (API §1)."""
    s = Settings(_env_file=None)
    assert s.cors_origins
    for origin in s.cors_origins:
        assert "127.0.0.1" in origin or "localhost" in origin
