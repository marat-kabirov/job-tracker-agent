"""Tools: load_resume_profile, compute_fit_score.

День 2 по плану (см. SPEC.md).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from mcp_server.schemas import (
    FitScoreResult,
    JobRequirements,
    RemotePreference,
    ResumeProfile,
    SeniorityLevel,
    Verdict,
)
from mcp_server.tools._llm import get_groq_llm

DEFAULT_RESUME_PATH = Path(
    os.environ.get("RESUME_PROFILE_PATH", "data/resume_profile.json")
)

# Пороги verdict по итоговому score. Вынесены в константы (не хардкодить
# в нескольких местах), см. TODO в SPEC.md: score >= GO_THRESHOLD -> go,
# MAYBE_THRESHOLD..GO_THRESHOLD-1 -> maybe, иначе -> no_go.
GO_THRESHOLD = 70
MAYBE_THRESHOLD = 50

# Верхняя граница score, когда сработал хотя бы один жёсткий фильтр —
# гарантирует no_go независимо от того, что насчитал LLM поверх.
HARD_FAIL_SCORE_CAP = MAYBE_THRESHOLD - 1

_SENIORITY_ORDER = {
    SeniorityLevel.junior: 0,
    SeniorityLevel.mid: 1,
    SeniorityLevel.senior: 2,
    SeniorityLevel.lead: 3,
}

# Фразы, по которым в сыром тексте вакансии эвристически ищем сигнал
# "спонсорство визы/рабочего разрешения не предоставляется". Грубая эвристика
# для MVP: сопоставляется только с резюме, где work_authorization явно
# говорит о потребности в спонсорстве.
_NO_SPONSORSHIP_PHRASES = (
    "no sponsorship",
    "not sponsor",
    "not able to sponsor",
    "unable to sponsor",
    "no visa sponsorship",
    "must have work authorization",
    "must be authorized to work",
)


def load_resume_profile(profile_id: str | None = None) -> ResumeProfile:
    """Читает профиль резюме из JSON и валидирует его через ResumeProfile.

    Для MVP `profile_id` игнорируется — один пользователь, один файл
    (data/resume_profile.json). Параметр оставлен в сигнатуре на случай,
    если понадобится несколько профилей под разные типы ролей.
    """
    data = _load_resume_json()
    return ResumeProfile.model_validate(data)


def _load_resume_json(path: Path = DEFAULT_RESUME_PATH) -> dict:
    """Вспомогательная функция для load_resume_profile."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _estimate_candidate_seniority(resume: ResumeProfile) -> SeniorityLevel:
    """Грубая оценка уровня кандидата по суммарному опыту.

    Это эвристика для детерминированного hard-filter'а, не замена
    полноценной seniority-модели — профиль не хранит явный seniority level.
    """
    years = resume.years_experience_total
    if years < 2:
        return SeniorityLevel.junior
    if years < 5:
        return SeniorityLevel.mid
    if years < 8:
        return SeniorityLevel.senior
    return SeniorityLevel.lead


def _language_base(lang: str) -> str:
    """Базовое название языка без уровня владения, напр. "English (C1)" -> "english"."""
    return lang.split("(")[0].strip().lower()


class _DeterministicMatch(BaseModel):
    matched_skills: list[str]
    missing_skills: list[str]
    hard_fail_reasons: list[str]
    stack_score: float | None = Field(
        description=(
            "Доля required_stack, покрытая резюме — exact-string матч плюс "
            "semantic-матч из фазы 2 (см. _semantic_skill_match), 0..1, "
            "None если required_stack пуст"
        )
    )
    semantic_match_notes: list[str] = Field(
        default_factory=list,
        description=(
            "Пояснения по пунктам, закрытым не буквальным совпадением строк, "
            "а семантическим решением LLM (фаза 2) — прокидываются в explanation, "
            "чтобы не выглядело так, будто это точное совпадение с резюме"
        ),
    )


class _SkillSemanticMatch(BaseModel):
    required_item: str = Field(description="required_stack item из вакансии, как есть")
    covered: bool = Field(
        description="Даёт ли резюме кандидата реальную, содержательную основу для этого требования"
    )
    matched_skill_name: str | None = Field(
        default=None,
        description="Название скилла из резюме, который покрывает required_item (только если covered=True)",
    )
    reason: str = Field(description="Короткое (1 предложение) обоснование решения")


class _SemanticMatchResponse(BaseModel):
    matches: list[_SkillSemanticMatch]


_SEMANTIC_MATCH_SYSTEM_PROMPT = """Ты помогаешь понять, покрывает ли резюме кандидата конкретные
пункты required_stack вакансии — даже если название в резюме и в вакансии не
совпадает буквально. Пример: вакансия просит "Next.js", в резюме нет пункта
"Next.js", но есть "React" и "TypeScript" — это разные, но содержательно
пересекающиеся технологии (Next.js — React-фреймворк), и опыт с React+TS даёт
реальную базу для Next.js.

Тебе дают список required_stack items, которые НЕ совпали по точному имени
ни с одним навыком кандидата, и полный список навыков кандидата (с годами
опыта и уровнем).

Для каждого item верни:
- covered=True, только если у навыков кандидата есть конкретная, содержательная
  техническая связь с этим item (тот же базовый стек/протокол/API семейство,
  на котором построен требуемый инструмент, а не просто "тоже про AI/бэкенд").
  Если связь слишком слабая или спекулятивная — covered=False. Не выдумывай
  компетенции, которых нет в данных.
- matched_skill_name — конкретное имя скилла кандидата, который покрывает
  item (только если covered=True, иначе null).
- reason — одно короткое предложение с обоснованием (в обе стороны: почему
  покрыто или почему нет).

Верни ровно один элемент matches на каждый входной required_stack item,
required_item в ответе — дословно как во входном списке.
"""


def _semantic_skill_match(
    unmatched_required: list[str], resume: ResumeProfile
) -> list[_SkillSemanticMatch]:
    """Фаза 2 skill-матчинга: LLM решает то, что не решается точным совпадением строк.

    Тот же принцип, что уже используется в _run_llm_assessment для
    explanation/score — здесь применён к самому skill-матчингу. Если LLM
    недоступен или не смог ответить структурированно — возвращаем пустой
    список (все item'ы остаются missing, а не ложно "покрытыми"): в этом
    шаге безопаснее деградировать в сторону no-match, а не угадывать.
    """
    if not unmatched_required or not resume.skills:
        return []

    llm = get_groq_llm()
    structured_llm = llm.with_structured_output(_SemanticMatchResponse)

    human_prompt = f"""required_stack items, не совпавшие по точному имени:
{unmatched_required}

Навыки кандидата (имя, годы опыта, уровень):
{[(s.name, s.years, s.proficiency.value) for s in resume.skills]}
"""

    try:
        result = structured_llm.invoke(
            [
                ("system", _SEMANTIC_MATCH_SYSTEM_PROMPT),
                ("human", human_prompt),
            ]
        )
    except Exception:
        return []

    if not isinstance(result, _SemanticMatchResponse):
        return []

    return result.matches


def _deterministic_match(job: JobRequirements, resume: ResumeProfile) -> _DeterministicMatch:
    """Skill-матчинг (двухфазный) + жёсткие фильтры.

    Фаза 1 — exact-string case-insensitive матч required_stack против навыков
    резюме: дёшево и надёжно там, где формулировки буквально совпадают.
    Фаза 2 (_semantic_skill_match) — то, что НЕ совпало в фазе 1, отдаётся
    одним LLM-вызовом: строки вроде "Next.js" (вакансия) и "React"/"TypeScript"
    (резюме) семантически пересекаются, но не совпадают как строки, и без
    LLM-шага такие пункты навсегда оставались бы в missing_skills. Это
    единственная не-детерминированная часть этой функции — hard-фильтры ниже
    (seniority/remote/location/язык/work_authorization) остаются полностью
    детерминированными: это факты, а не суждение, и семантического разрыва
    у них нет (в отличие от вольной лексики required_stack).
    """
    resume_skill_names = {s.name.strip().lower() for s in resume.skills}
    required = [s.strip() for s in job.required_stack if s.strip()]

    exact_matched = [s for s in required if s.lower() in resume_skill_names]
    exact_missing = [s for s in required if s.lower() not in resume_skill_names]

    semantic_matches = _semantic_skill_match(exact_missing, resume)
    semantic_by_key = {
        m.required_item.strip().lower(): m
        for m in semantic_matches
        if m.covered and m.matched_skill_name
    }

    matched = list(exact_matched)
    missing: list[str] = []
    semantic_match_notes: list[str] = []

    for item in exact_missing:
        sem = semantic_by_key.get(item.strip().lower())
        if sem is None:
            missing.append(item)
            continue
        matched.append(item)
        semantic_match_notes.append(
            f'"{item}" покрыт через semantic match (не точное совпадение с резюме) '
            f'навыком "{sem.matched_skill_name}": {sem.reason}'
        )

    stack_score = len(matched) / len(required) if required else None

    hard_fail_reasons: list[str] = []

    candidate_level = _estimate_candidate_seniority(resume)
    if _SENIORITY_ORDER[job.seniority_level] - _SENIORITY_ORDER[candidate_level] >= 2:
        hard_fail_reasons.append(
            f"seniority gap: вакансия требует {job.seniority_level.value}, "
            f"профиль ближе к {candidate_level.value} "
            f"(~{resume.years_experience_total:g} лет опыта)"
        )

    if resume.remote_preference == RemotePreference.remote_only and not job.remote_ok:
        hard_fail_reasons.append(
            "remote mismatch: профиль ищет только remote, вакансия remote не предлагает"
        )

    if not job.remote_ok and job.location and resume.preferred_location:
        location_lower = job.location.lower()
        if not any(
            loc.lower() in location_lower or location_lower in loc.lower()
            for loc in resume.preferred_location
        ):
            hard_fail_reasons.append(
                f"location mismatch: вакансия в {job.location!r}, "
                f"профиль предпочитает {resume.preferred_location}"
            )

    if job.language_requirements and resume.languages:
        # Сравниваем только базовое название языка (до скобки с уровнем),
        # не весь текст: "English (C1)" и "English (C1 or above)" — один и
        # тот же язык, а проверка уровня владения — не факт, а суждение,
        # это отдаётся LLM-шагу, а не хардкодится здесь.
        resume_langs_base = {_language_base(lang) for lang in resume.languages}
        if not any(
            _language_base(req) in resume_langs_base for req in job.language_requirements
        ):
            hard_fail_reasons.append(
                f"language mismatch: вакансия требует {job.language_requirements}, "
                f"профиль указывает {resume.languages}"
            )

    needs_sponsorship = "sponsor" in resume.work_authorization.lower() and (
        "no sponsorship needed" not in resume.work_authorization.lower()
    )
    if needs_sponsorship and any(
        phrase in job.raw_text.lower() for phrase in _NO_SPONSORSHIP_PHRASES
    ):
        hard_fail_reasons.append(
            "work_authorization mismatch: вакансия явно не спонсирует визу/разрешение, "
            f"профиль указывает {resume.work_authorization!r}"
        )

    return _DeterministicMatch(
        matched_skills=matched,
        missing_skills=missing,
        hard_fail_reasons=hard_fail_reasons,
        stack_score=stack_score,
        semantic_match_notes=semantic_match_notes,
    )


class _LLMScoreAssessment(BaseModel):
    score: int = Field(ge=0, le=100, description="Итоговый fit score 0-100")
    explanation: str = Field(description="2-4 предложения объяснения score")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Насколько уверенно можно судить по доступным данным"
    )


_SCORE_SYSTEM_PROMPT = """Ты помогаешь оценить, насколько кандидат подходит под вакансию.

Тебе уже дан результат детерминированного анализа: пересечение обязательного
стека вакансии с навыками кандидата, и список сработавших жёстких фильтров
(seniority/remote/location/язык/work authorization — если этот список не пуст,
речь идёт о доказанном несоответствии, а не предположении).

Часть matched_skills могла быть покрыта не точным совпадением строк, а
semantic match (см. semantic_match_notes) — например, вакансия просит
"Next.js", а у кандидата есть "React"/"TypeScript". Это реальное, но более
слабое покрытие, чем прямой опыт с самим инструментом.

Твоя задача — поверх этих фактов:
- учесть nice-to-have стек (плюс, но не обязательный),
- учесть неявные сигналы из текста вакансии (culture fit, формулировки,
  red flags вроде "rockstar ninja", нереалистичные требования, неясные
  обязанности),
- дать итоговый score 0-100 и объяснение на 2-4 предложения.

Правила:
- Если hard_fail_reasons не пуст — это дисквалифицирующие факторы, score
  должен быть низким (не выше 40), независимо от остального совпадения.
- Если required_stack не удалось извлечь (stack_score = null) — снижай
  confidence, не выдумывай уверенность на пустом месте.
- score должен быть согласован с детерминированным stack_score как базовой
  линией: отклоняйся от неё только когда для этого есть явная причина
  (сильное покрытие nice-to-have, явные red flags в тексте и т.п.), и
  объясняй это отклонение в explanation.
- Если semantic_match_notes не пуст — явно упомяни в explanation, что часть
  покрытия стека основана на смежном опыте, а не на прямом использовании
  требуемого инструмента. Не подавай semantic match как эквивалент прямого
  опыта — это должно быть видно читателю explanation, а не скрыто.
- НЕ штрафуй score за years_experience_total сам по себе. Оценка разрыва по
  годам/уровню опыта — это зона ответственности hard_fail_reasons
  (seniority gap уже проверяется детерминированно до тебя): если вакансия
  явно требует определённый стаж/уровень и кандидат ему не соответствует,
  это уже отражено в hard_fail_reasons, и штрафовать за это ещё раз в своей
  оценке не нужно — это задвоение одного и того же сигнала. Если явного
  требования к годам/уровню опыта в raw_text нет (а hard_fail_reasons по
  seniority пуст) — years_experience_total вообще не повод понижать score;
  оценивай fit по стеку и soft-сигналам, не оглядываясь на общий стаж.
"""


def compute_fit_score(job: JobRequirements, resume: ResumeProfile) -> FitScoreResult:
    """Считает fit-score.

    1. Детерминированная часть (_deterministic_match): пересечение
       required_stack и навыков резюме + жёсткие фильтры (факты, не суждение).
    2. LLM-часть поверх шага 1: рассуждение по неявным сигналам, формирует
       explanation и предлагает итоговый score/confidence.
    3. verdict считается по порогу (GO_THRESHOLD/MAYBE_THRESHOLD) от итогового
       score, а не запрашивается у LLM напрямую — так порог остаётся
       единственным местом, где решается go/maybe/no_go.
    """
    det = _deterministic_match(job, resume)

    llm_result = _run_llm_assessment(job, resume, det)

    score = llm_result.score
    if det.hard_fail_reasons:
        score = min(score, HARD_FAIL_SCORE_CAP)

    verdict = _verdict_from_score(score)

    return FitScoreResult(
        score=score,
        verdict=verdict,
        matched_skills=det.matched_skills,
        missing_skills=det.missing_skills,
        explanation=llm_result.explanation,
        confidence=llm_result.confidence,
    )


def _run_llm_assessment(
    job: JobRequirements, resume: ResumeProfile, det: _DeterministicMatch
) -> _LLMScoreAssessment:
    llm = get_groq_llm()
    structured_llm = llm.with_structured_output(_LLMScoreAssessment)

    stack_score_pct = (
        f"{det.stack_score * 100:.0f}%" if det.stack_score is not None else "неизвестно (required_stack пуст)"
    )
    human_prompt = f"""Вакансия:
title: {job.title}
company: {job.company}
seniority_level: {job.seniority_level.value}
required_stack: {job.required_stack}
nice_to_have_stack: {job.nice_to_have_stack}
location: {job.location}
remote_ok: {job.remote_ok}
language_requirements: {job.language_requirements}
salary_range: {job.salary_range}

Текст вакансии целиком (для оценки формулировок/red flags):
{job.raw_text}

Профиль кандидата:
years_experience_total: {resume.years_experience_total}
skills: {[(s.name, s.years, s.proficiency.value) for s in resume.skills]}
languages: {resume.languages}
remote_preference: {resume.remote_preference.value}
preferred_location: {resume.preferred_location}
work_authorization: {resume.work_authorization}
past_roles: {resume.past_roles}

Детерминированный анализ (уже посчитан, не пересчитывай):
matched_skills: {det.matched_skills}
missing_skills: {det.missing_skills}
stack_score: {stack_score_pct}
hard_fail_reasons: {det.hard_fail_reasons}
semantic_match_notes (пункты matched_skills, покрытые смежным опытом, а не
буквальным совпадением — см. правило про semantic match выше): {det.semantic_match_notes}
"""

    try:
        result = structured_llm.invoke(
            [
                ("system", _SCORE_SYSTEM_PROMPT),
                ("human", human_prompt),
            ]
        )
    except Exception:
        result = None

    if isinstance(result, _LLMScoreAssessment):
        return result

    # LLM недоступен/не смог ответить структурированно — fallback на чистый
    # детерминированный score, чтобы tool не падал (тот же принцип, что и
    # в extract_job_requirements: честный частичный результат лучше ошибки).
    fallback_score = round(det.stack_score * 100) if det.stack_score is not None else MAYBE_THRESHOLD
    return _LLMScoreAssessment(
        score=fallback_score,
        explanation=(
            "LLM-оценка недоступна (ошибка вызова Groq) — score посчитан только по "
            "детерминированному пересечению required_stack с навыками профиля."
        ),
        confidence=0.3,
    )


def _verdict_from_score(score: int) -> Verdict:
    if score >= GO_THRESHOLD:
        return Verdict.go
    if score >= MAYBE_THRESHOLD:
        return Verdict.maybe
    return Verdict.no_go
