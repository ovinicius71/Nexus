"""Tests for the similarity-threshold calibration (Phase 10)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from organizer.calibrate import THRESHOLD_KEY, calibrate, run_calibration
from organizer.db.repository import EntryRepository


def test_calibrate_needs_enough_samples() -> None:
    result = calibrate([(0.8, True), (0.3, False)], min_samples=10)
    assert result.enough is False
    assert result.n_pos == 1 and result.n_neg == 1


def test_calibrate_needs_both_classes() -> None:
    samples = [(0.8, True)] * 12  # only positives
    result = calibrate(samples, min_samples=10)
    assert result.enough is False


def test_calibrate_finds_separating_threshold() -> None:
    # Accepted links cluster high, rejected low: a threshold near 0.6 separates them.
    samples = [(s, True) for s in [0.9, 0.85, 0.8, 0.7, 0.65]]
    samples += [(s, False) for s in [0.5, 0.45, 0.4, 0.3, 0.2]]

    result = calibrate(samples, min_samples=8)

    assert result.enough is True
    assert result.f1 == 1.0  # perfectly separable
    assert 0.5 < result.threshold <= 0.65  # boundary sits between the clusters
    assert result.n_pos == 5 and result.n_neg == 5


def _connection(repo: EntryRepository, sim: float, accepted: bool) -> None:
    a = repo.add_raw_entry("a")
    b = repo.add_raw_entry("b")
    conn = repo.add_pending_connection(a.id, b.id, sim)
    repo.set_connection_accepted(conn.id, accepted)


def test_run_calibration_persists_learned_threshold(session: Session) -> None:
    repo = EntryRepository(session)
    for sim in [0.9, 0.85, 0.8, 0.75, 0.7]:
        _connection(repo, sim, True)
    for sim in [0.5, 0.45, 0.4, 0.35, 0.3]:
        _connection(repo, sim, False)

    result = run_calibration(session, min_samples=8)

    assert result.enough is True
    stored = repo.get_setting(THRESHOLD_KEY)
    assert stored is not None
    assert abs(float(stored) - result.threshold) < 1e-6


def test_run_calibration_does_not_persist_when_insufficient(session: Session) -> None:
    repo = EntryRepository(session)
    _connection(repo, 0.8, True)
    _connection(repo, 0.3, False)

    result = run_calibration(session, min_samples=10)

    assert result.enough is False
    assert repo.get_setting(THRESHOLD_KEY) is None


def test_app_setting_roundtrip_and_update(session: Session) -> None:
    repo = EntryRepository(session)
    assert repo.get_setting("k") is None
    repo.set_setting("k", "1")
    assert repo.get_setting("k") == "1"
    repo.set_setting("k", "2")  # update path
    assert repo.get_setting("k") == "2"
