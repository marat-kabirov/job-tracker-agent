"""Tools: log_application, update_application_outcome, query_tracker_stats.

День 3 по плану (см. SPEC.md): SQLite через SQLAlchemy, одна таблица
applications — плоская проекция ApplicationRecord.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

from mcp_server.schemas import FitScoreResult, JobRequirements, TrackerStats

DEFAULT_DB_PATH = Path(os.environ.get("TRACKER_DB_PATH", "data/tracker.db"))


def log_application(
    job: JobRequirements, fit: FitScoreResult, decision: str
) -> str:
    """Пишет запись в SQLite-трекер, возвращает application_id.

    TODO (день 3):
      - SQLAlchemy engine/session на DEFAULT_DB_PATH
      - модель Application (плоская проекция ApplicationRecord из schemas.py)
      - id — просто uuid4, дата applied_at — now()
    """
    raise NotImplementedError(
        "log_application не реализован — см. TODO в mcp_server/tools/tracker.py"
    )


def update_application_outcome(
    application_id: str, outcome: str, outcome_date: datetime | None = None
) -> bool:
    """Обновляет запись, когда приходит реальный ответ на заявку.

    TODO (день 3): найти запись по id, проставить outcome/outcome_at.
    В MVP обновляется вручную через CLI-команду (`cli.py update <id> <outcome>`);
    авто-обновление через email-парсер — идея для README "что бы я сделал дальше".
    """
    raise NotImplementedError(
        "update_application_outcome не реализован — см. TODO в mcp_server/tools/tracker.py"
    )


def query_tracker_stats(since: date | None = None) -> TrackerStats:
    """Агрегаты по трекеру: сколько заявок, среднее время до отказа,
    score-распределение по исходам, доля go-решений с отказом.

    TODO (день 3): один SELECT с группировкой по outcome + пара агрегатов
    в Python поверх выгруженных строк — сложная аналитика (percentiles и т.п.)
    для MVP не нужна.
    """
    raise NotImplementedError(
        "query_tracker_stats не реализован — см. TODO в mcp_server/tools/tracker.py"
    )
