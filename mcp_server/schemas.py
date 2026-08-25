"""Pydantic-схемы данных проекта.

Контракты входа/выхода для всех MCP tools и для state LangGraph-агента.
См. раздел "Структуры данных" в SPEC.md — там же обоснование полей.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Proficiency(str, Enum):
    junior = "junior"
    mid = "mid"
    senior = "senior"


class SeniorityLevel(str, Enum):
    junior = "junior"
    mid = "mid"
    senior = "senior"
    lead = "lead"


class RemotePreference(str, Enum):
    remote_only = "remote_only"
    hybrid_ok = "hybrid_ok"
    onsite_ok = "onsite_ok"


class Verdict(str, Enum):
    go = "go"
    maybe = "maybe"
    no_go = "no_go"


class Decision(str, Enum):
    applied = "applied"
    skipped = "skipped"


class Outcome(str, Enum):
    rejected = "rejected"
    interview = "interview"
    ghosted = "ghosted"
    offer = "offer"


# ---------------------------------------------------------------------------
# Профиль резюме
# ---------------------------------------------------------------------------


class SkillEntry(BaseModel):
    name: str
    years: float = Field(ge=0)
    proficiency: Proficiency


class ResumeProfile(BaseModel):
    skills: list[SkillEntry]
    years_experience_total: float = Field(ge=0)
    languages: list[str] = Field(
        description="Рабочие/разговорные языки, не языки программирования"
    )
    work_authorization: str = Field(
        description='напр. "EU work permit required" / "no sponsorship needed"'
    )
    preferred_location: list[str]
    remote_preference: RemotePreference
    past_roles: list[str] = Field(
        description="Краткие тайтлы прошлых ролей, для seniority-контекста"
    )


# ---------------------------------------------------------------------------
# Вакансия
# ---------------------------------------------------------------------------


class JobRequirements(BaseModel):
    title: str
    company: str
    required_stack: list[str]
    nice_to_have_stack: list[str] = Field(default_factory=list)
    seniority_level: SeniorityLevel
    language_requirements: list[str] = Field(default_factory=list)
    location: str
    remote_ok: bool
    salary_range: str | None = None
    raw_text: str


# ---------------------------------------------------------------------------
# Результат скоринга
# ---------------------------------------------------------------------------


class FitScoreResult(BaseModel):
    score: int = Field(ge=0, le=100)
    verdict: Verdict
    matched_skills: list[str]
    missing_skills: list[str]
    explanation: str = Field(description="Reasoning trace, 2-4 предложения")
    confidence: float = Field(ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Запись в трекере заявок
# ---------------------------------------------------------------------------


class ApplicationRecord(BaseModel):
    id: str
    job: JobRequirements
    fit: FitScoreResult
    decision: Decision
    applied_at: datetime
    outcome: Outcome | None = None
    outcome_at: datetime | None = None


class TrackerStats(BaseModel):
    since: date | None = None
    total_applications: int
    applications_by_outcome: dict[str, int]
    average_score: float
    average_score_by_outcome: dict[str, float]
    average_time_to_rejection_hours: float | None = None
    go_decisions_that_were_rejected: int = Field(
        description="Сколько заявок с verdict=go всё равно получили отказ — сигнал, что скоринг завышает"
    )
