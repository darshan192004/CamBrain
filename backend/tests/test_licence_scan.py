"""Prove the licence scan fails on AGPL — including a planted dependency."""

from __future__ import annotations

from scripts.check_licences import DENIED_PACKAGES, find_agpl_violations


def test_detects_agpl_in_licence_expression() -> None:
    assert find_agpl_violations([("somepkg", "AGPL-3.0-or-later")])


def test_detects_agpl_in_classifier_text() -> None:
    hits = find_agpl_violations(
        [("somepkg", "License :: OSI Approved :: GNU Affero General Public License v3")]
    )
    assert len(hits) == 1


def test_allows_every_permitted_licence() -> None:
    """Permissive licences must never trip the gate — a noisy gate gets disabled."""
    for licence in ("MIT", "Apache-2.0", "BSD-3-Clause", "BSD", "MPL-2.0", ""):
        assert find_agpl_violations([("somepkg", licence)]) == [], licence


def test_plain_gpl_is_not_flagged_as_agpl() -> None:
    """GPL and AGPL are different obligations. Conflating them would either
    block permitted dependencies or, worse, teach us to ignore the gate."""
    assert find_agpl_violations([("lgplv3", "LGPL-3.0-or-later")]) == []
    assert find_agpl_violations([("gplpkg", "GPL-3.0-only")]) == []


def test_ultralytics_is_denied_even_with_empty_metadata() -> None:
    """The known offender is banned by name; metadata cannot clear it."""
    assert "ultralytics" in DENIED_PACKAGES
    assert find_agpl_violations([("ultralytics", "")]) == ["ultralytics (denied by name)"]


def test_case_insensitive_detection() -> None:
    assert find_agpl_violations([("somepkg", "agpl-3.0")])


def test_reports_every_violation_not_just_the_first() -> None:
    """A one-line-at-a-time report turns a licence audit into a guessing game."""
    hits = find_agpl_violations([("a", "AGPL-3.0"), ("b", "MIT"), ("c", "Affero GPL")])
    assert len(hits) == 2
