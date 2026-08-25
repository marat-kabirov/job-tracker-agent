"""Тесты tracker.py — на временной SQLite базе, не на data/tracker.db.

TRACKER_DB_PATH переопределяется через monkeypatch на файл в tmp_path;
tracker.py читает переменную окружения при каждом вызове (см.
_resolve_db_path), так что переопределение работает без переимпорта модуля.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from mcp_server.schemas import (
    FitScoreResult,
    JobRequirements,
    SeniorityLevel,
    Verdict,
)
from mcp_server.tools import tracker


@pytest.fixture(autouse=True)
def temp_tracker_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_tracker.db"
    monkeypatch.setenv("TRACKER_DB_PATH", str(db_path))
    return db_path


def _make_job(**overrides) -> JobRequirements:
    defaults = dict(
        title="Backend Engineer",
        company="Acme",
        required_stack=["Python", "FastAPI"],
        seniority_level=SeniorityLevel.mid,
        location="Berlin",
        remote_ok=True,
        raw_text="Backend Engineer at Acme. Python, FastAPI required.",
    )
    defaults.update(overrides)
    return JobRequirements(**defaults)


def _make_fit(**overrides) -> FitScoreResult:
    defaults = dict(
        score=80,
        verdict=Verdict.go,
        matched_skills=["Python", "FastAPI"],
        missing_skills=[],
        explanation="Strong match.",
        confidence=0.9,
    )
    defaults.update(overrides)
    return FitScoreResult(**defaults)


def test_log_application_then_stats_finds_record():
    job = _make_job()
    fit = _make_fit()

    application_id = tracker.log_application(job, fit, "applied")

    assert application_id

    stats = tracker.query_tracker_stats()

    assert stats.total_applications == 1
    assert stats.average_score == 80.0
    assert stats.applications_by_outcome == {"pending": 1}
    assert stats.average_time_to_rejection_hours is None
    assert stats.go_decisions_that_were_rejected == 0


def test_update_application_outcome_updates_existing_record():
    job = _make_job()
    fit = _make_fit()
    application_id = tracker.log_application(job, fit, "applied")

    ok = tracker.update_application_outcome(application_id, "interview")

    assert ok is True

    stats = tracker.query_tracker_stats()
    assert stats.applications_by_outcome == {"interview": 1}


def test_update_application_outcome_returns_false_for_unknown_id():
    ok = tracker.update_application_outcome("does-not-exist", "rejected")

    assert ok is False


def test_stats_compute_average_time_to_rejection_and_go_rejected_count():
    job = _make_job()
    fit = _make_fit(score=85, verdict=Verdict.go)
    application_id = tracker.log_application(job, fit, "applied")

    outcome_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=3)
    tracker.update_application_outcome(application_id, "rejected", outcome_date=outcome_at)

    stats = tracker.query_tracker_stats()

    assert stats.applications_by_outcome == {"rejected": 1}
    assert stats.go_decisions_that_were_rejected == 1
    assert stats.average_time_to_rejection_hours is not None
    assert stats.average_time_to_rejection_hours == pytest.approx(3.0, abs=0.1)


def test_stats_since_filters_out_older_records():
    job = _make_job()
    fit = _make_fit()
    tracker.log_application(job, fit, "applied")

    future_since = (datetime.now(UTC).replace(tzinfo=None) + timedelta(days=1)).date()
    stats = tracker.query_tracker_stats(since=future_since)

    assert stats.total_applications == 0
    assert stats.since == future_since
