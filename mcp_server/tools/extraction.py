"""Tools: fetch_job_posting, extract_job_requirements.

День 2 по плану (см. SPEC.md): здесь появится реальный LLM-вызов для
extract_job_requirements и HTTP-фетч + html->text очистка для fetch_job_posting.
"""

from __future__ import annotations

from mcp_server.schemas import JobRequirements


def fetch_job_posting(url: str) -> str:
    """Скачивает вакансию по URL и возвращает очищенный текст.

    TODO (день 2):
      - HTTP GET с разумным timeout и User-Agent
      - вырезать nav/footer/script через что-то вроде trafilatura или readability-lxml
      - вернуть чистый текст объявления, без верстки

    Можно временно не реализовывать: MVP умеет принимать текст вакансии
    напрямую, без скачивания по URL (см. SPEC.md, "что можно вырезать первым").
    """
    raise NotImplementedError(
        "fetch_job_posting не реализован — см. TODO в mcp_server/tools/extraction.py"
    )


def extract_job_requirements(raw_text: str) -> JobRequirements:
    """LLM-извлечение структурированных полей из текста вакансии.

    TODO (день 2):
      - промпт, который просит модель вернуть JSON, валидируемый как JobRequirements
        (structured output / tool-calling на стороне LLM-провайдера, не ручной парсинг)
      - если required_stack пустой или модель сама сигнализирует низкую уверенность —
        это тот случай, который в LangGraph-графе уходит в узел `clarify`
        (решение о том, что делать с низкой уверенностью, принимает граф,
        а не этот tool — tool должен честно вернуть то, что смог извлечь)
    """
    raise NotImplementedError(
        "extract_job_requirements не реализован — см. TODO в mcp_server/tools/extraction.py"
    )
