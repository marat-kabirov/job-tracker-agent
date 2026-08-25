"""MCP-сервер: регистрирует все инструменты проекта.

Запуск: python -m mcp_server.server
(поднимает stdio-транспорт — стандартно для локального клиента вроде
Claude Desktop / LangGraph MCP client)

Инструменты пока не реализованы (см. TODO в mcp_server/tools/*.py) — сервер
поднимается и tools видны клиенту через list_tools, но вызов упадёт с
NotImplementedError. Это ожидаемо для дня 1: цель — зафиксировать контракты
(сигнатуры + Pydantic-схемы), реализация — день 2-3.
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from mcp_server.tools.extraction import extract_job_requirements, fetch_job_posting
from mcp_server.tools.scoring import compute_fit_score, load_resume_profile
from mcp_server.tools.tracker import (
    log_application,
    query_tracker_stats,
    update_application_outcome,
)

# MCPServer — актуальный (mcp>=2.0) API SDK, замена более старому FastMCP
# из mcp.server.fastmcp (тот модуль в 2.x удалён). API совместим один в один:
# тот же .tool() декоратор, тот же .run() со stdio-транспортом по умолчанию.
mcp = MCPServer("job-tracker-agent")

# Регистрация tools. Держим определения функций отдельно от регистрации
# (в mcp_server/tools/*.py), чтобы их можно было юнит-тестить и переиспользовать
# в LangGraph-графе напрямую, без похода через MCP-протокол при локальной отладке.
mcp.tool()(fetch_job_posting)
mcp.tool()(extract_job_requirements)
mcp.tool()(load_resume_profile)
mcp.tool()(compute_fit_score)
mcp.tool()(log_application)
mcp.tool()(update_application_outcome)
mcp.tool()(query_tracker_stats)


if __name__ == "__main__":
    mcp.run()
