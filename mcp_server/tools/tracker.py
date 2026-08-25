"""Tools: log_application, update_application_outcome, query_tracker_stats.

SQLite (через SQLAlchemy) с одной таблицей `applications` — плоская
проекция ApplicationRecord из schemas.py: job/fit хранятся как JSON-блобы
(вложенные Pydantic-модели), остальные поля — обычные колонки.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import mean

from sqlalchemy import JSON, DateTime, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from mcp_server.schemas import (
    Decision,
    FitScoreResult,
    JobRequirements,
    Outcome,
    TrackerStats,
    Verdict,
)

DEFAULT_DB_PATH = Path("data/tracker.db")

# Ключ, под которым в TrackerStats.applications_by_outcome /
# average_score_by_outcome группируются заявки без outcome (ещё не пришёл
# ответ) — не смешиваем с реальными значениями Outcome enum.
_PENDING_OUTCOME_KEY = "pending"


def _utcnow() -> datetime:
    # Naive UTC (не tz-aware): ApplicationRecord.applied_at/outcome_at в
    # schemas.py — обычный datetime без требования timezone, а SQLite
    # DateTime-колонка всё равно не хранит tzinfo — используем naive
    # везде, чтобы избежать aware/naive рассинхрона при вычитании дат.
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class ApplicationORM(Base):
    __tablename__ = "applications"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    job: Mapped[dict] = mapped_column(JSON)
    fit: Mapped[dict] = mapped_column(JSON)
    decision: Mapped[str] = mapped_column(String)
    applied_at: Mapped[datetime] = mapped_column(DateTime)
    outcome: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


def _resolve_db_path() -> Path:
    # Читаем env на каждый вызов (не кэшируем в module-level константу),
    # чтобы тесты могли подменить TRACKER_DB_PATH на временный файл без
    # переимпорта модуля.
    return Path(os.environ.get("TRACKER_DB_PATH", str(DEFAULT_DB_PATH)))


def _get_engine():
    db_path = _resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    return engine


def log_application(job: JobRequirements, fit: FitScoreResult, decision: str) -> str:
    """Пишет запись в SQLite-трекер, возвращает application_id."""
    # Валидирует decision через enum — если граф передаст что-то за пределами
    # applied/skipped, это баг вызывающего кода, а не то, что стоит тихо проглотить.
    decision_value = Decision(decision).value

    application_id = str(uuid.uuid4())
    engine = _get_engine()
    with Session(engine) as session:
        record = ApplicationORM(
            id=application_id,
            job=job.model_dump(mode="json"),
            fit=fit.model_dump(mode="json"),
            decision=decision_value,
            applied_at=_utcnow(),
        )
        session.add(record)
        session.commit()

    return application_id


def update_application_outcome(
    application_id: str, outcome: str, outcome_date: datetime | None = None
) -> bool:
    """Обновляет запись, когда приходит реальный ответ на заявку.

    Возвращает False, если заявка с таким id не найдена (вместо исключения —
    это ожидаемый случай при опечатке в id, вызывающий код сам решает, что
    с этим делать).
    """
    outcome_value = Outcome(outcome).value

    engine = _get_engine()
    with Session(engine) as session:
        record = session.get(ApplicationORM, application_id)
        if record is None:
            return False

        record.outcome = outcome_value
        record.outcome_at = outcome_date or _utcnow()
        session.commit()

    return True


def query_tracker_stats(since: date | None = None) -> TrackerStats:
    """Агрегаты по трекеру: один SELECT + группировка/агрегаты в Python.

    Записи без outcome группируются под ключом "pending" — это тоже полезный
    сигнал (сколько заявок всё ещё без ответа), не шум, который стоит выкинуть.
    """
    engine = _get_engine()
    stmt = select(ApplicationORM)
    if since is not None:
        stmt = stmt.where(ApplicationORM.applied_at >= datetime.combine(since, datetime.min.time()))

    with Session(engine) as session:
        records = session.scalars(stmt).all()

    total = len(records)

    scores_by_outcome: dict[str, list[float]] = {}
    rejection_hours: list[float] = []
    go_decisions_that_were_rejected = 0

    for record in records:
        outcome_key = record.outcome or _PENDING_OUTCOME_KEY
        scores_by_outcome.setdefault(outcome_key, []).append(record.fit["score"])

        if record.outcome == Outcome.rejected.value and record.outcome_at is not None:
            delta_hours = (record.outcome_at - record.applied_at).total_seconds() / 3600
            rejection_hours.append(delta_hours)

        if (
            record.fit.get("verdict") == Verdict.go.value
            and record.outcome == Outcome.rejected.value
        ):
            go_decisions_that_were_rejected += 1

    all_scores = [s for scores in scores_by_outcome.values() for s in scores]

    return TrackerStats(
        since=since,
        total_applications=total,
        applications_by_outcome={
            outcome: len(scores) for outcome, scores in scores_by_outcome.items()
        },
        average_score=mean(all_scores) if all_scores else 0.0,
        average_score_by_outcome={
            outcome: mean(scores) for outcome, scores in scores_by_outcome.items()
        },
        average_time_to_rejection_hours=mean(rejection_hours) if rejection_hours else None,
        go_decisions_that_were_rejected=go_decisions_that_were_rejected,
    )
