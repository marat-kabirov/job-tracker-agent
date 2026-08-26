"""Юнит-тесты skill-матчинга и жёстких фильтров.

_deterministic_match теперь двухфазный: фаза 1 — exact-string матч (чисто
детерминированная, без сети), фаза 2 — _semantic_skill_match, один LLM-вызов
на required_stack items, не совпавшие в фазе 1 (см. scoring.py). Чтобы
большинство тестов здесь оставались без сети/без Groq (это по-прежнему нужно
для быстрого прогона — compute_fit_score целиком с реальным LLM покрыт в
test_pipeline_llm.py), фаза 2 замокана автоматически (см.
mock_semantic_skill_match ниже) на "ничего не покрыто". Тесты, которые
проверяют саму семантическую логику, либо подменяют мок вручную
(monkeypatch), либо помечены @pytest.mark.real_semantic_match и бьют по
настоящему Groq (см. requires_groq).
"""

from __future__ import annotations

import pytest

from mcp_server.schemas import (
    ResumeProfile,
    SeniorityLevel,
    SkillEntry,
)
from mcp_server.schemas import JobRequirements
from mcp_server.tools import scoring
from mcp_server.tools.scoring import (
    GO_THRESHOLD,
    MAYBE_THRESHOLD,
    _deterministic_match,
    _SkillSemanticMatch,
    _verdict_from_score,
    load_resume_profile,
)

from .conftest import requires_groq


@pytest.fixture(autouse=True)
def mock_semantic_skill_match(request, monkeypatch):
    """По умолчанию фаза 2 (_semantic_skill_match) замокана на "ничего не
    покрыто" — большинство тестов в этом файле проверяют exact-match/
    hard-filter логику и не должны зависеть от реального вызова Groq.
    Тесты, помеченные @pytest.mark.real_semantic_match, используют настоящую
    функцию (нужен GROQ_API_KEY — см. requires_groq).
    """
    if request.node.get_closest_marker("real_semantic_match"):
        return
    monkeypatch.setattr(scoring, "_semantic_skill_match", lambda unmatched, resume: [])


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


# ---------------------------------------------------------------------------
# Фаза 2: semantic skill match (день-4 фикс семантического gap из eval'а —
# см. _KNOWN_MISMATCH_NOTES в evals/run_eval.py: "Next.js" required vs резюме
# без "Next.js", но с "React"+"TypeScript" — раньше навсегда оставалось
# в missing_skills, теперь _semantic_skill_match может закрыть такой разрыв.
# ---------------------------------------------------------------------------


def test_semantic_match_moves_covered_item_from_missing_to_matched(monkeypatch):
    resume = _make_resume(
        skills=[
            SkillEntry(name="React", years=3, proficiency="mid"),
            SkillEntry(name="TypeScript", years=3, proficiency="mid"),
        ]
    )
    job = _make_job(required_stack=["Next.js"])

    monkeypatch.setattr(
        scoring,
        "_semantic_skill_match",
        lambda unmatched, resume: [
            _SkillSemanticMatch(
                required_item="Next.js",
                covered=True,
                matched_skill_name="React",
                reason="Next.js is a React framework and the candidate has React+TypeScript experience.",
            )
        ],
    )

    result = _deterministic_match(job, resume)

    assert result.matched_skills == ["Next.js"]
    assert result.missing_skills == []
    assert result.stack_score == 1.0
    assert len(result.semantic_match_notes) == 1
    assert "Next.js" in result.semantic_match_notes[0]
    assert "React" in result.semantic_match_notes[0]
    assert "semantic match" in result.semantic_match_notes[0]


def test_semantic_match_not_covered_stays_in_missing(monkeypatch):
    resume = _make_resume(
        skills=[SkillEntry(name="Python", years=5, proficiency="senior")]
    )
    job = _make_job(required_stack=["Kubernetes"])

    monkeypatch.setattr(
        scoring,
        "_semantic_skill_match",
        lambda unmatched, resume: [
            _SkillSemanticMatch(
                required_item="Kubernetes",
                covered=False,
                matched_skill_name=None,
                reason="No container orchestration experience in the profile.",
            )
        ],
    )

    result = _deterministic_match(job, resume)

    assert result.matched_skills == []
    assert result.missing_skills == ["Kubernetes"]
    assert result.stack_score == 0.0
    assert result.semantic_match_notes == []


@pytest.mark.real_semantic_match
def test_semantic_match_skips_llm_call_when_nothing_is_missing(monkeypatch):
    """_deterministic_match всегда вызывает _semantic_skill_match, но сама
    _semantic_skill_match должна коротко замкнуться до похода к Groq, если
    unmatched_required пуст — используем настоящую _semantic_skill_match
    (real_semantic_match отключает автомок) и шпионим на get_groq_llm, чтобы
    убедиться, что до сети дело не доходит."""
    resume = _make_resume()
    job = _make_job(required_stack=["Python", "FastAPI"])  # оба покрыты фазой 1

    def fail_if_called(*args, **kwargs):
        raise AssertionError("get_groq_llm не должен вызываться, если нечего доматчивать")

    monkeypatch.setattr(scoring, "get_groq_llm", fail_if_called)

    result = _deterministic_match(job, resume)

    assert result.matched_skills == ["Python", "FastAPI"]
    assert result.missing_skills == []


@pytest.mark.real_semantic_match
@requires_groq
def test_semantic_match_recognizes_nextjs_via_react_and_typescript_live():
    """Настоящий Groq-вызов (фаза 2, без мока): required_stack=["Next.js"], в
    резюме нет "Next.js", но есть "React"+"TypeScript" — должно матчиться
    через semantic match, а не оставаться в missing_skills навсегда."""
    resume = _make_resume(
        skills=[
            SkillEntry(name="React", years=3, proficiency="senior"),
            SkillEntry(name="TypeScript", years=3, proficiency="senior"),
        ]
    )
    job = _make_job(required_stack=["Next.js"])

    result = _deterministic_match(job, resume)

    assert result.matched_skills == ["Next.js"]
    assert result.missing_skills == []
    assert result.stack_score == 1.0
    assert len(result.semantic_match_notes) == 1
