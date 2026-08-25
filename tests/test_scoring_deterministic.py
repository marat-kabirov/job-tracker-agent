"""Юнит-тесты детерминированной части скоринга — без сети, без Groq.

compute_fit_score целиком (с LLM-вызовом) покрыт в test_pipeline_llm.py.
Здесь проверяется только keyword-матч стека и жёсткие фильтры
(_deterministic_match) плюс verdict-по-порогу и чтение резюме.
"""

from __future__ import annotations

from mcp_server.schemas import (
    ResumeProfile,
    SeniorityLevel,
    SkillEntry,
)
from mcp_server.schemas import JobRequirements
from mcp_server.tools.scoring import (
    GO_THRESHOLD,
    MAYBE_THRESHOLD,
    _deterministic_match,
    _verdict_from_score,
    load_resume_profile,
)


def _make_resume(**overrides) -> ResumeProfile:
    defaults = dict(
        skills=[
            SkillEntry(name="Python", years=5, proficiency="senior"),
            SkillEntry(name="FastAPI", years=3, proficiency="mid"),
        ],
        years_experience_total=5,
        languages=["English (C1)"],
        work_authorization="no sponsorship needed",
        preferred_location=["Berlin", "Remote EU"],
        remote_preference="hybrid_ok",
        past_roles=["Backend Engineer"],
    )
    defaults.update(overrides)
    return ResumeProfile(**defaults)


def _make_job(**overrides) -> JobRequirements:
    defaults = dict(
        title="Backend Engineer",
        company="Acme",
        required_stack=["Python", "FastAPI"],
        seniority_level=SeniorityLevel.mid,
        location="Berlin",
        remote_ok=False,
        raw_text="Backend Engineer at Acme. Python, FastAPI required.",
    )
    defaults.update(overrides)
    return JobRequirements(**defaults)


def test_deterministic_match_full_stack_overlap_no_hard_fail():
    resume = _make_resume()
    job = _make_job()

    result = _deterministic_match(job, resume)

    assert set(result.matched_skills) == {"Python", "FastAPI"}
    assert result.missing_skills == []
    assert result.hard_fail_reasons == []
    assert result.stack_score == 1.0


def test_deterministic_match_missing_skill_is_reported():
    resume = _make_resume()
    job = _make_job(required_stack=["Python", "Kubernetes"])

    result = _deterministic_match(job, resume)

    assert result.matched_skills == ["Python"]
    assert result.missing_skills == ["Kubernetes"]
    assert result.stack_score == 0.5


def test_deterministic_match_empty_required_stack_has_no_stack_score():
    resume = _make_resume()
    job = _make_job(required_stack=[])

    result = _deterministic_match(job, resume)

    assert result.matched_skills == []
    assert result.missing_skills == []
    assert result.stack_score is None


def test_hard_fail_on_remote_only_candidate_vs_onsite_job():
    resume = _make_resume(remote_preference="remote_only")
    job = _make_job(remote_ok=False)

    result = _deterministic_match(job, resume)

    assert any("remote mismatch" in reason for reason in result.hard_fail_reasons)


def test_hard_fail_on_seniority_gap():
    resume = _make_resume(years_experience_total=1)  # ~junior
    job = _make_job(seniority_level=SeniorityLevel.lead)

    result = _deterministic_match(job, resume)

    assert any("seniority gap" in reason for reason in result.hard_fail_reasons)


def test_no_hard_fail_when_location_matches_and_remote_not_required():
    resume = _make_resume(preferred_location=["Berlin"])
    job = _make_job(location="Berlin, Germany", remote_ok=False)

    result = _deterministic_match(job, resume)

    assert not any("location mismatch" in reason for reason in result.hard_fail_reasons)


def test_hard_fail_on_work_authorization_conflict():
    resume = _make_resume(work_authorization="requires visa sponsorship")
    job = _make_job(
        raw_text="We are not able to sponsor visas for this role. Python, FastAPI required."
    )

    result = _deterministic_match(job, resume)

    assert any(
        "work_authorization mismatch" in reason for reason in result.hard_fail_reasons
    )


def test_verdict_from_score_thresholds():
    assert _verdict_from_score(GO_THRESHOLD).value == "go"
    assert _verdict_from_score(GO_THRESHOLD - 1).value == "maybe"
    assert _verdict_from_score(MAYBE_THRESHOLD).value == "maybe"
    assert _verdict_from_score(MAYBE_THRESHOLD - 1).value == "no_go"


def test_load_resume_profile_reads_and_validates_default_file():
    profile = load_resume_profile()

    assert isinstance(profile, ResumeProfile)
    assert len(profile.skills) > 0
