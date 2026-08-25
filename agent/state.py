"""LangGraph state.

День 3 по плану (см. SPEC.md, "LangGraph-агент: узлы графа"). Здесь только
форма state — сам граф с узлами ingest/extract/retrieve_profile/score/decide/
log/clarify собирается в graph.py.
"""

from __future__ import annotations

from typing import TypedDict

from mcp_server.schemas import FitScoreResult, JobRequirements, ResumeProfile


class AgentState(TypedDict, total=False):
    # вход
    raw_input: str  # текст вакансии ИЛИ url — ingest-узел решает, что это
    is_url: bool

    # накапливается по ходу графа
    raw_text: str
    job: JobRequirements
    resume: ResumeProfile
    fit: FitScoreResult

    # решение
    decision: str  # "applied" | "skipped"
    application_id: str

    # для ветки clarify: почему извлечение не удалось / низкая уверенность
    needs_clarification: bool
    clarification_reason: str | None
