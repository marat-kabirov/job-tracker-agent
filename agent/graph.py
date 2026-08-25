"""LangGraph-граф: ingest -> extract -> retrieve_profile -> score -> decide -> log,
с веткой clarify при низкой уверенности извлечения.

День 3 по плану (см. SPEC.md). Пока — только скелет узлов и рёбер, без
реализации (тела узлов вызывают tools из mcp_server/tools/*, которые сами
пока NotImplementedError — граф начнёт реально работать, когда будут готовы
и tools, и эти узлы).
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from agent.state import AgentState


def ingest(state: AgentState) -> AgentState:
    """Нормализует raw_input (текст или URL) в raw_text."""
    raise NotImplementedError("TODO день 3: ingest")


def extract(state: AgentState) -> AgentState:
    """Вызывает extract_job_requirements, наполняет state['job']."""
    raise NotImplementedError("TODO день 3: extract")


def retrieve_profile(state: AgentState) -> AgentState:
    """Вызывает load_resume_profile, наполняет state['resume']."""
    raise NotImplementedError("TODO день 3: retrieve_profile")


def score(state: AgentState) -> AgentState:
    """Вызывает compute_fit_score, наполняет state['fit']."""
    raise NotImplementedError("TODO день 3: score")


def decide(state: AgentState) -> AgentState:
    """Применяет порог verdict -> decision (applied/skipped)."""
    raise NotImplementedError("TODO день 3: decide")


def log(state: AgentState) -> AgentState:
    """Вызывает log_application, наполняет state['application_id']."""
    raise NotImplementedError("TODO день 3: log")


def clarify(state: AgentState) -> AgentState:
    """Ветка для расплывчатых вакансий: просит уточнение вместо score."""
    raise NotImplementedError("TODO день 3: clarify")


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
