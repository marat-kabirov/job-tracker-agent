"""Tools: load_resume_profile, compute_fit_score.

День 2 по плану (см. SPEC.md).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from mcp_server.schemas import FitScoreResult, JobRequirements, ResumeProfile

DEFAULT_RESUME_PATH = Path(
    os.environ.get("RESUME_PROFILE_PATH", "data/resume_profile.json")
)


def load_resume_profile(profile_id: str | None = None) -> ResumeProfile:
    """Читает профиль резюме из JSON.

    Для MVP `profile_id` игнорируется — один пользователь, один файл
    (data/resume_profile.json). Параметр оставлен в сигнатуре на случай,
    если понадобится несколько профилей под разные типы ролей.

    TODO (день 2): дописать реальное чтение + валидацию через ResumeProfile.
    Сейчас — заглушка, чтобы MCP-сервер поднимался и tool был виден клиенту.
    """
    raise NotImplementedError(
        "load_resume_profile не реализован — см. TODO в mcp_server/tools/scoring.py.\n"
        f"Файл профиля должен лежать в {DEFAULT_RESUME_PATH}"
    )


def compute_fit_score(
    job: JobRequirements, resume: ResumeProfile
) -> FitScoreResult:
    """Считает fit-score.

    TODO (день 2), по SPEC.md:
      1. Детерминированная часть: пересечение job.required_stack и
         {s.name for s in resume.skills} → matched_skills / missing_skills.
         Плюс жёсткие фильтры: seniority_level, remote_ok vs remote_preference,
         work_authorization vs location — это то, что не должно решать LLM,
         это факты, а не суждение.
      2. LLM-часть: рассуждение по неявным сигналам (nice_to_have, формулировки,
         red flags в тексте вакансии) поверх результатов шага 1 — здесь и
         рождается explanation и итоговый score/verdict.
      3. verdict по порогу: score >= 70 -> go, 50-69 -> maybe, иначе no_go
         (порог вынести в конфиг, не хардкодить в нескольких местах).
    """
    raise NotImplementedError(
        "compute_fit_score не реализован — см. TODO в mcp_server/tools/scoring.py"
    )


def _load_resume_json(path: Path = DEFAULT_RESUME_PATH) -> dict:
    """Вспомогательная функция для будущей реализации load_resume_profile."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)
