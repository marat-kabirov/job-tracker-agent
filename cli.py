"""CLI точка входа.

День 3 по плану: `python cli.py score --file posting.txt`, `python cli.py stats`,
`python cli.py update <application_id> <outcome>`.
"""

from __future__ import annotations

import typer

app = typer.Typer(help="AI Job Application Tracker Agent — CLI")


@app.command()
def score(
    file: str = typer.Option(None, help="Путь к файлу с текстом вакансии"),
    url: str = typer.Option(None, help="URL вакансии"),
) -> None:
    """Прогнать вакансию через агента, получить fit-score и решение."""
    raise NotImplementedError("TODO день 3: cli score -> agent.graph.build_graph()")


@app.command()
def stats(since: str = typer.Option(None, help="YYYY-MM-DD")) -> None:
    """Показать агрегаты по трекеру заявок."""
    raise NotImplementedError("TODO день 3: cli stats -> query_tracker_stats")


@app.command()
def update(application_id: str, outcome: str) -> None:
    """Проставить реальный исход заявки (rejected/interview/ghosted/offer)."""
    raise NotImplementedError(
        "TODO день 3: cli update -> update_application_outcome"
    )


if __name__ == "__main__":
    app()
