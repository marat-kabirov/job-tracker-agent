"""Общий helper для получения Groq LLM-клиента.

Вынесено отдельно, чтобы extraction.py и scoring.py не дублировали
инициализацию ChatGroq. Используем Groq (бесплатный тариф) вместо
Anthropic API — ключ в .env как GROQ_API_KEY (langchain-groq подхватывает
его автоматически через переменную окружения).
"""

from __future__ import annotations

import os

from langchain_groq import ChatGroq

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"


def get_groq_llm(temperature: float = 0.0) -> ChatGroq:
    """Создаёт ChatGroq-клиент.

    Модель берётся из GROQ_MODEL (env), если задана, иначе используется
    DEFAULT_GROQ_MODEL. Список моделей Groq меняется часто — на момент
    реализации `llama-3.3-70b-versatile` (упомянутая изначально в задаче)
    была снята с бесплатного тарифа/удалена из GET /v1/models для этого
    ключа (404 model_not_found), поэтому дефолт — openai/gpt-oss-120b:
    актуальная production-модель Groq с поддержкой tool calling /
    structured output, проверено вызовом. См. актуальный список на
    console.groq.com/docs/models — он периодически меняется.
    """
    model = os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL)
    return ChatGroq(model=model, temperature=temperature)
