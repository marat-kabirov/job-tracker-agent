"""CLI точка входа.

`python cli.py score --file posting.txt`, `python cli.py stats`,
`python cli.py update <application_id> <outcome>`.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import typer
from dotenv import load_dotenv

load_dotenv()

# Windows-консоль по умолчанию открывает stdout в cp1252/cp866 и падает на
# юникод-символах (тире, кавычки и т.п.) из LLM-объяснений — переключаем на
# utf-8, чтобы `python cli.py score` не крашился посреди вывода.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.graph import build_graph  # noqa: E402
from mcp_server.schemas import Outcome  # noqa: E402
from mcp_server.tools.tracker import (  # noqa: E402
    query_tracker_stats,
    update_application_outcome,
)

app = typer.Typer(help="AI Job Application Tracker Agent — CLI")


@app.command()
def score(
    file: str = typer.Option(None, help="Путь к файлу с текстом вакансии"),
    url: str = typer.Option(None, help="URL вакансии"),
) -> None:
    """Прогнать вакансию через агента, получить fit-score и решение."""
    if url:
        typer.echo(
            "URL пока не поддерживается: fetch_job_posting сознательно не "
            "реализован (см. SPEC.md, день 2). Передай текст вакансии через --file."
        )
        raise typer.Exit(code=1)

    if not file:
        typer.echo("Нужно передать --file с текстом вакансии.")
        raise typer.Exit(code=1)

    raw_text = Path(file).read_text(encoding="utf-8")

    graph = build_graph().compile()
    result = graph.invoke({"raw_input": raw_text, "is_url": False})

    if result.get("needs_clarification"):
        typer.echo(result.get("clarification_reason") or "Вакансия неясна, нужна ручная проверка.")
        return

    job = result["job"]
    fit = result["fit"]

    typer.echo(f"{job.title} @ {job.company}")
    typer.echo(f"Verdict: {fit.verdict.value}   Score: {fit.score}/100   Decision: {result['decision']}")
    typer.echo(f"Matched skills: {', '.join(fit.matched_skills) or '—'}")
    typer.echo(f"Missing skills: {', '.join(fit.missing_skills) or '—'}")
    typer.echo(f"Explanation: {fit.explanation}")
    typer.echo(f"Confidence: {fit.confidence:.2f}")
    typer.echo(f"Application ID: {result['application_id']}")


@app.command()
def stats(since: str = typer.Option(None, help="YYYY-MM-DD")) -> None:
    """Показать агрегаты по трекеру заявок."""
    since_date = date.fromisoformat(since) if since else None
    result = query_tracker_stats(since_date)

    typer.echo(f"Всего заявок: {result.total_applications}")
    if result.since:
        typer.echo(f"С {result.since.isoformat()}")
    typer.echo(f"Средний score: {result.average_score:.1f}")

    typer.echo("По исходам:")
    for outcome, count in result.applications_by_outcome.items():
        avg = result.average_score_by_outcome.get(outcome)
        avg_str = f"{avg:.1f}" if avg is not None else "—"
        typer.echo(f"  {outcome}: {count} (средний score {avg_str})")

    if result.average_time_to_rejection_hours is not None:
        typer.echo(f"Среднее время до отказа: {result.average_time_to_rejection_hours:.1f} ч")

    typer.echo(f"Go-решений, получивших отказ: {result.go_decisions_that_were_rejected}")


@app.command()
def update(application_id: str, outcome: str) -> None:
    """Проставить реальный исход заявки (rejected/interview/ghosted/offer)."""
    try:
        Outcome(outcome)
    except ValueError:
        valid = ", ".join(o.value for o in Outcome)
        typer.echo(f"Неизвестный outcome {outcome!r}. Допустимые значения: {valid}.")
        raise typer.Exit(code=1)

    ok = update_application_outcome(application_id, outcome)
    if ok:
        typer.echo(f"Обновлено: {application_id} -> {outcome}")
    else:
        typer.echo(f"Заявка {application_id} не найдена.")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
