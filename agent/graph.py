"""LangGraph-граф: ingest -> extract -> retrieve_profile -> score -> decide -> log,
с веткой clarify при низкой уверенности извлечения.

День 3 по плану (см. SPEC.md). Verdict (go/maybe/no_go) и итоговый score уже
посчитаны в compute_fit_score (день 2, mcp_server/tools/scoring.py) — граф
не переизобретает эту логику, только читает FitScoreResult.verdict и мапит
его на decision (applied/skipped).
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from agent.state import AgentState
from mcp_server.schemas import Decision, Verdict
from mcp_server.tools.extraction import extract_job_requirements
from mcp_server.tools.scoring import compute_fit_score, load_resume_profile
from mcp_server.tools.tracker import log_application


def ingest(state: AgentState) -> AgentState:
    """Нормализует raw_input (текст или URL) в raw_text.

    MVP не реализует fetch_job_posting (см. день 2/SPEC.md — сознательно
    вырезано первым), поэтому здесь предполагается, что на вход всегда
    приходит текст вакансии, а не URL: raw_input кладётся в raw_text как есть.
    """
    return {"raw_text": state["raw_input"]}


def extract(state: AgentState) -> AgentState:
    """Вызывает extract_job_requirements, наполняет state['job'].

    Если required_stack пустой, LLM-извлечение не смогло распознать
    требования вакансии — граф уходит в узел `clarify` вместо того, чтобы
    гадать со score на пустых данных.
    """
    job = extract_job_requirements(state["raw_text"])

    if not job.required_stack:
        return {
            "job": job,
            "needs_clarification": True,
            "clarification_reason": (
                "Не удалось распознать обязательные технологии (required_stack пуст). "
                "Текст вакансии слишком расплывчатый, либо LLM-извлечение не справилось — "
                "проверь текст вручную или уточни требования вакансии."
            ),
        }

    return {"job": job, "needs_clarification": False, "clarification_reason": None}


def retrieve_profile(state: AgentState) -> AgentState:
    """Вызывает load_resume_profile, наполняет state['resume']."""
    return {"resume": load_resume_profile()}


def score(state: AgentState) -> AgentState:
    """Вызывает compute_fit_score, наполняет state['fit']."""
    return {"fit": compute_fit_score(state["job"], state["resume"])}


def decide(state: AgentState) -> AgentState:
    """Применяет verdict -> decision: go/maybe -> applied, no_go -> skipped."""
    verdict = state["fit"].verdict
    decision = Decision.skipped if verdict == Verdict.no_go else Decision.applied
    return {"decision": decision.value}


def log(state: AgentState) -> AgentState:
    """Вызывает log_application, наполняет state['application_id']."""
    application_id = log_application(state["job"], state["fit"], state["decision"])
    return {"application_id": application_id}


def clarify(state: AgentState) -> AgentState:
    """Ветка для расплывчатых вакансий: просит уточнение вместо score.

    Ничего не логирует в трекер — нечего логировать без score/decision.
    """
    reason = state.get("clarification_reason") or "Вакансия недостаточно ясна для оценки."
    message = f"Нужна ручная проверка перед оценкой этой вакансии.\nПричина: {reason}"
    return {"clarification_reason": message}


def _needs_clarification(state: AgentState) -> str:
    """Роутер после extract: в clarify или дальше в retrieve_profile."""
    return "clarify" if state.get("needs_clarification") else "retrieve_profile"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("ingest", ingest)
    graph.add_node("extract", extract)
    graph.add_node("retrieve_profile", retrieve_profile)
    graph.add_node("score", score)
    graph.add_node("decide", decide)
    graph.add_node("log", log)
    graph.add_node("clarify", clarify)

    graph.set_entry_point("ingest")
    graph.add_edge("ingest", "extract")
    graph.add_conditional_edges(
        "extract",
        _needs_clarification,
        {"clarify": "clarify", "retrieve_profile": "retrieve_profile"},
    )
    graph.add_edge("retrieve_profile", "score")
    graph.add_edge("score", "decide")
    graph.add_edge("decide", "log")
    graph.add_edge("log", END)
    graph.add_edge("clarify", END)

    return graph
