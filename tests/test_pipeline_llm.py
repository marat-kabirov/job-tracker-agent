"""End-to-end тест реального пути: raw_text -> JobRequirements -> FitScoreResult.

Делает настоящие вызовы Groq (llama-3.3-70b-versatile по умолчанию), поэтому
требует GROQ_API_KEY в окружении/.env — без него тесты пропускаются
(см. conftest.requires_groq), а не падают, чтобы `pytest` оставался зелёным
в окружении без ключа.
"""

from __future__ import annotations

from mcp_server.schemas import (
    FitScoreResult,
    JobRequirements,
    ResumeProfile,
    SkillEntry,
    Verdict,
)
from mcp_server.tools.extraction import extract_job_requirements
from mcp_server.tools.scoring import compute_fit_score

from .conftest import requires_groq

JOB_POSTING_TEXT = """
Senior Backend Engineer (AI Platform) — Nordic Signal

Nordic Signal is building an AI-powered platform for financial document
analysis. We are looking for a Senior Backend Engineer to join our small,
remote-first team.

What you'll do:
- Design and build backend services in Python (FastAPI) that power our
  LLM-based document extraction pipeline
- Build and maintain RAG pipelines using LangChain and FAISS for retrieval
  over large document sets
- Own our PostgreSQL data layer via SQLAlchemy, including schema design and
  migrations
- Collaborate with the ML team on evaluation and prompt iteration

Required:
- 5+ years of professional backend engineering experience
- Strong Python and FastAPI experience
- Hands-on experience with LangChain and RAG pipelines in production
- Experience with SQLAlchemy and relational databases
- Comfortable working in a fully remote, async-first team

Nice to have:
- Experience with LangGraph or other agent orchestration frameworks
- Experience with TypeScript/React for internal tooling
- Familiarity with vector search (FAISS, pgvector, or similar)

Location: Remote (EU timezones)
This is a fully remote position open to candidates anywhere in the EU.
Languages: English (C1 or above) required for daily standups and
documentation.
Salary: EUR 70,000-90,000 depending on experience.
"""


@requires_groq
def test_extract_job_requirements_on_real_posting():
    job = extract_job_requirements(JOB_POSTING_TEXT)

    assert isinstance(job, JobRequirements)
    assert job.raw_text == JOB_POSTING_TEXT
    assert job.remote_ok is True

    stack_lower = {s.lower() for s in job.required_stack}
    assert "python" in stack_lower
    assert "fastapi" in stack_lower
    # required_stack не должен быть пустым для явно расписанной вакансии —
    # это тот сигнал, из-за отсутствия которого граф уходит в узел `clarify`.
    assert len(job.required_stack) > 0


@requires_groq
def test_compute_fit_score_end_to_end_good_match():
    job = extract_job_requirements(JOB_POSTING_TEXT)

    resume = ResumeProfile(
        skills=[
            SkillEntry(name="Python", years=6, proficiency="senior"),
            SkillEntry(name="FastAPI", years=4, proficiency="senior"),
            SkillEntry(name="LangChain", years=2, proficiency="mid"),
            SkillEntry(name="SQLAlchemy", years=5, proficiency="senior"),
            SkillEntry(name="PostgreSQL", years=5, proficiency="senior"),
            SkillEntry(name="RAG pipelines", years=2, proficiency="mid"),
            SkillEntry(name="LangGraph", years=1, proficiency="mid"),
            SkillEntry(name="FAISS / vector search", years=1, proficiency="mid"),
            SkillEntry(name="TypeScript", years=3, proficiency="mid"),
            SkillEntry(name="React", years=3, proficiency="mid"),
        ],
        years_experience_total=6,
        languages=["English (C1)"],
        work_authorization="no sponsorship needed, EU work permit",
        preferred_location=["Remote EU", "Berlin"],
        remote_preference="remote_only",
        past_roles=["Backend Engineer", "Senior Backend Engineer"],
    )

    fit = compute_fit_score(job, resume)

    assert isinstance(fit, FitScoreResult)
    assert 0 <= fit.score <= 100
    assert fit.verdict in set(Verdict)
    assert "Python" in fit.matched_skills
    assert fit.explanation
    assert 0.0 <= fit.confidence <= 1.0
    # Сильное совпадение по стеку + подходящий seniority/remote/язык не должны
    # давать no_go при отсутствии сработавших жёстких фильтров.
    assert fit.verdict != Verdict.no_go
