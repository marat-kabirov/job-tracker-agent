"""End-to-end smoke-тест графа с замоканными tools — не дёргает Groq/SQLite.

extraction.py/scoring.py уже протестированы на реальном Groq (день 2,
test_pipeline_llm.py); tracker.py — на временной SQLite (test_tracker.py).
Здесь проверяется только сборка/роутинг графа: ingest -> extract ->
retrieve_profile -> score -> decide -> log, и ветка extract -> clarify.
"""

from __future__ import annotations

import agent.graph as graph_module
from mcp_server.schemas import (
    FitScoreResult,
    JobRequirements,
    ResumeProfile,
    SeniorityLevel,
    SkillEntry,
    Verdict,
)


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


def _make_resume() -> ResumeProfile:
    return ResumeProfile(
        skills=[SkillEntry(name="Python", years=5, proficiency="senior")],
        years_experience_total=5,
        languages=["English (C1)"],
        work_authorization="no sponsorship needed",
        preferred_location=["Berlin"],
        remote_preference="hybrid_ok",
        past_roles=["Backend Engineer"],
    )


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


def test_graph_happy_path_logs_application_for_go_verdict(monkeypatch):
    job = _make_job()
    resume = _make_resume()
    fit = _make_fit(verdict=Verdict.go, score=85)

    monkeypatch.setattr(graph_module, "extract_job_requirements", lambda raw_text: job)
    monkeypatch.setattr(graph_module, "load_resume_profile", lambda: resume)
    monkeypatch.setattr(graph_module, "compute_fit_score", lambda j, r: fit)

    logged_calls = []

    def fake_log_application(job_arg, fit_arg, decision_arg):
        logged_calls.append((job_arg, fit_arg, decision_arg))
        return "fake-application-id"

    monkeypatch.setattr(graph_module, "log_application", fake_log_application)

    app = graph_module.build_graph().compile()
    result = app.invoke({"raw_input": "Backend Engineer at Acme.", "is_url": False})

    assert result["needs_clarification"] is False
    assert result["job"] == job
    assert result["resume"] == resume
    assert result["fit"] == fit
    assert result["decision"] == "applied"
    assert result["application_id"] == "fake-application-id"

    assert len(logged_calls) == 1
    assert logged_calls[0] == (job, fit, "applied")


def test_graph_no_go_verdict_still_logs_as_skipped(monkeypatch):
    job = _make_job()
    resume = _make_resume()
    fit = _make_fit(verdict=Verdict.no_go, score=20)

    monkeypatch.setattr(graph_module, "extract_job_requirements", lambda raw_text: job)
    monkeypatch.setattr(graph_module, "load_resume_profile", lambda: resume)
    monkeypatch.setattr(graph_module, "compute_fit_score", lambda j, r: fit)
    monkeypatch.setattr(
        graph_module, "log_application", lambda job_arg, fit_arg, decision_arg: "skipped-id"
    )

    app = graph_module.build_graph().compile()
    result = app.invoke({"raw_input": "irrelevant text", "is_url": False})

    assert result["decision"] == "skipped"
    assert result["application_id"] == "skipped-id"


def test_graph_routes_to_clarify_when_required_stack_empty(monkeypatch):
    vague_job = _make_job(required_stack=[])

    monkeypatch.setattr(graph_module, "extract_job_requirements", lambda raw_text: vague_job)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("должно было уйти в clarify, а не дальше по графу")

    monkeypatch.setattr(graph_module, "load_resume_profile", fail_if_called)
    monkeypatch.setattr(graph_module, "compute_fit_score", fail_if_called)
    monkeypatch.setattr(graph_module, "log_application", fail_if_called)

    app = graph_module.build_graph().compile()
    result = app.invoke({"raw_input": "some vague posting", "is_url": False})

    assert result["needs_clarification"] is True
    assert "required_stack" in result["clarification_reason"]
    assert "application_id" not in result
    assert "fit" not in result
