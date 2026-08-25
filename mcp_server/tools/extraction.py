"""Tools: fetch_job_posting, extract_job_requirements.

День 2 по плану (см. SPEC.md): здесь появится реальный LLM-вызов для
extract_job_requirements и HTTP-фетч + html->text очистка для fetch_job_posting.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from mcp_server.schemas import JobRequirements, SeniorityLevel
from mcp_server.tools._llm import get_groq_llm


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


class _ExtractedFields(BaseModel):
    """Промежуточная схема для structured output.

    Без `raw_text` — он уже известен вызывающему (это вход функции), просить
    модель повторить его в ответе — лишние токены и риск, что она его исказит.
    Все поля с дефолтами: если модель не смогла что-то извлечь из текста,
    tool должен вернуть частичный результат, а не упасть с ошибкой валидации
    (решение о том, что делать с пустым/неполным результатом, принимает
    LangGraph-граф в узле `clarify`, не этот tool).
    """

    title: str = Field(default="", description="Название позиции")
    company: str = Field(default="", description="Название компании")
    required_stack: list[str] = Field(
        default_factory=list,
        description=(
            "Технологии/навыки, явно указанные как обязательные требования. "
            "Не включай сюда nice-to-have и не выдумывай то, чего нет в тексте."
        ),
    )
    nice_to_have_stack: list[str] = Field(
        default_factory=list,
        description="Технологии, упомянутые как желательные/плюс, но не обязательные",
    )
    seniority_level: SeniorityLevel = Field(
        default=SeniorityLevel.mid,
        description="Уровень позиции по тексту вакансии",
    )
    language_requirements: list[str] = Field(
        default_factory=list,
        description='Требуемые разговорные/рабочие языки, напр. "English (C1)"',
    )
    location: str = Field(default="", description="Город/страна/регион вакансии")
    remote_ok: bool = Field(
        default=False, description="Явно ли допускается удалённая работа"
    )
    salary_range: str | None = Field(default=None)


_SYSTEM_PROMPT = """Ты — парсер вакансий (job postings). Тебе дают сырой текст вакансии.
Извлеки из него структурированные поля строго по предоставленной схеме.

Правила:
- Используй только то, что явно следует из текста. Не выдумывай и не додумывай.
- Если поле нельзя однозначно определить из текста — оставь значение по умолчанию
  (пустая строка / пустой список / False), не гадай.
- required_stack — только по-настоящему обязательные технологии/навыки
  ("required", "must have", "you will need"). Всё, что помечено как плюс,
  желательно или "nice to have", идёт в nice_to_have_stack.
- remote_ok = true, только если в тексте явно сказано про удалённую работу
  (remote, work from home, distributed team и т.п.).
"""


def extract_job_requirements(raw_text: str) -> JobRequirements:
    """LLM-извлечение структурированных полей из текста вакансии.

    Вызывает Groq (ChatGroq) через langchain with_structured_output — модель
    сама валидирует ответ под Pydantic-схему (function calling), без ручного
    regex-парсинга JSON.

    Если required_stack пустой или сам LLM-вызов не удался (сеть, rate limit,
    модель не смогла сформировать валидный structured output) — tool не падает,
    а честно возвращает то, что смог извлечь (в худшем случае — почти пустой
    JobRequirements с raw_text). Решение, что делать с низкой уверенностью
    (пустой required_stack), принимает LangGraph-граф в узле `clarify`.
    """
    llm = get_groq_llm()
    structured_llm = llm.with_structured_output(_ExtractedFields)

    try:
        extracted = structured_llm.invoke(
            [
                ("system", _SYSTEM_PROMPT),
                ("human", raw_text),
            ]
        )
    except Exception:
        # Намеренно широкий catch: сетевые ошибки, ошибки Groq API, ошибки
        # парсинга structured output — во всех случаях контракт tool'а
        # требует не падать, а вернуть честный частичный результат.
        extracted = _ExtractedFields()

    if not isinstance(extracted, _ExtractedFields):
        extracted = _ExtractedFields()

    return JobRequirements(
        title=extracted.title,
        company=extracted.company,
        required_stack=extracted.required_stack,
        nice_to_have_stack=extracted.nice_to_have_stack,
        seniority_level=extracted.seniority_level,
        language_requirements=extracted.language_requirements,
        location=extracted.location,
        remote_ok=extracted.remote_ok,
        salary_range=extracted.salary_range,
        raw_text=raw_text,
    )
