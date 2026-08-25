# AI Job Application Tracker Agent — технический scope

## Идея одной строкой

Агент, который читает вакансию, извлекает требования через MCP tools, сравнивает их с профилем резюме, выдаёт fit-score с объяснением, логирует решение в трекер заявок и постепенно накапливает статистику по всему job-серчу — то есть автоматизирует ровно ту ручную работу, которую сейчас делает сам автор при разборе вакансий вроде GeneralMind, Manex AI, Lucid Labs и WaveSix.

## Архитектура

Система состоит из трёх слоёв, которые физически можно держать в одном репозитории, но логически они разделены.

MCP-сервер отвечает за всё, что можно оформить как переиспользуемый инструмент: парсинг вакансии, доступ к профилю резюме, скоринг и запись в трекер. Он ничего не знает про то, в каком порядке его инструменты вызываются — это забота агента.

LangGraph-агент — это клиент MCP-сервера. Он держит state (что уже извлечено, какой score получен, какое решение принято) и прогоняет граф из узлов: приём вакансии → извлечение требований → подтяжка профиля → скоринг → решение go/no-go → запись в трекер → (опционально) черновик сопроводительного письма.

Tracker-слой — это персистентное хранилище (SQLite через SQLAlchemy, раз это уже часть стека) со всеми обработанными вакансиями, их score и реальными исходами (отклик, отказ, интервью, тишина). Именно это делает проект "tracker", а не разовым скорером: через 2-3 недели использования на нём можно будет строить ту же аналитику, что сейчас делается вручную ("отказ пришёл через час после подачи на сильный keyword-мэтч").

Точка входа — простой CLI (`python -m tracker score --url ... ` или `--file posting.txt`), FastAPI слой опционален и не обязателен для MVP.

```
Job posting (text/URL)
        │
        ▼
  LangGraph agent  ── state: JobRequirements, ResumeProfile, FitScoreResult
        │  (вызывает MCP tools по мере прохождения графа)
        ▼
   MCP Server ── extract_requirements / load_resume_profile /
                 compute_fit_score / log_application / query_tracker_stats
        │
        ▼
   SQLite (tracker.db) + resume_profile.json / FAISS index
```

## MCP-сервер: инструменты

Это ядро проекта — именно набор tools и их контракты стоит зафиксировать до кода, потому что дизайн инструментов определяет дизайн графа.

| Tool | Вход | Выход | Что делает |
|---|---|---|---|
| `fetch_job_posting` | `url: str` | `raw_text: str` | Скачивает и чистит HTML вакансии до текста (для случая, когда на входе URL, а не текст) |
| `extract_job_requirements` | `raw_text: str` | `JobRequirements` | LLM-извлечение структурированных полей из текста вакансии (см. схему ниже) |
| `load_resume_profile` | `profile_id: str \| None` | `ResumeProfile` | Читает профиль резюме/скиллов из JSON (или подтягивает релевантные чанки из FAISS, если резюме большое и разбито на секции) |
| `compute_fit_score` | `JobRequirements, ResumeProfile` | `FitScoreResult` | Считает score: часть — детерминированный keyword-матч (stack, seniority, язык, локация), часть — LLM-рассуждение по неявным сигналам (culture fit, formulation red flags) |
| `log_application` | `JobRequirements, FitScoreResult, decision: str` | `application_id: str` | Пишет запись в SQLite-трекер |
| `update_application_outcome` | `application_id: str, outcome: str, outcome_date` | `ok: bool` | Обновляет запись, когда приходит реальный ответ (отказ/интервью/тишина) — заполняется вручную или через будущий email-парсер |
| `query_tracker_stats` | `since: date \| None` | `TrackerStats` | Агрегаты: сколько заявок, среднее время до отказа, score-распределение по исходам — то, что сейчас считается в голове |

Первая версия может обойтись без `fetch_job_posting` (только текст на входе) и без `update_application_outcome` (обновление статусов вручную через простой CLI-командой) — это первое, что можно вырезать, если время поджимает.

## Структуры данных

Все модели — Pydantic, чтобы MCP tools отдавали и принимали валидированный JSON без ручного парсинга.

```python
class ResumeProfile(BaseModel):
    skills: list[SkillEntry]        # {name, years, proficiency: junior|mid|senior}
    years_experience_total: float
    languages: list[str]            # разговорные/рабочие языки, не только языки программирования
    work_authorization: str         # напр. "EU work permit required" / "no sponsorship needed"
    preferred_location: list[str]
    remote_preference: str          # remote_only | hybrid_ok | onsite_ok
    past_roles: list[str]           # краткие тайтлы, для seniority-контекста

class JobRequirements(BaseModel):
    title: str
    company: str
    required_stack: list[str]
    nice_to_have_stack: list[str]
    seniority_level: str            # junior | mid | senior | lead
    language_requirements: list[str]
    location: str
    remote_ok: bool
    salary_range: str | None
    raw_text: str

class FitScoreResult(BaseModel):
    score: int                      # 0–100
    verdict: str                    # go | maybe | no_go
    matched_skills: list[str]
    missing_skills: list[str]
    explanation: str                # reasoning trace, 2-4 предложения
    confidence: float               # 0–1, насколько LLM уверена в своей оценке

class ApplicationRecord(BaseModel):
    id: str
    job: JobRequirements
    fit: FitScoreResult
    decision: str                   # applied | skipped
    applied_at: datetime
    outcome: str | None             # rejected | interview | ghosted | offer
    outcome_at: datetime | None
```

## LangGraph-агент: узлы графа

State — это по сути один объект, собирающий все поля выше по ходу выполнения.

Узел `ingest` принимает текст или URL и нормализует его в `raw_text`. Узел `extract` вызывает `extract_job_requirements`. Узел `retrieve_profile` вызывает `load_resume_profile`. Узел `score` вызывает `compute_fit_score`. Узел `decide` применяет порог (например score ≥ 70 → go, 50–69 → maybe, ниже → no_go) и решает, логировать ли заявку как "applied" или "skipped". Узел `log` вызывает `log_application`. Финальный узел возвращает пользователю человекочитаемый summary — именно то сообщение, которое сейчас пишется вручную после разбора вакансии.

Ветвление нужно ровно одно: если `extract_job_requirements` вернул низкую уверенность или пустой `required_stack` (вакансия слишком расплывчатая), граф уходит в узел `clarify`, который просит уточнение вместо того, чтобы гадать со score.

## Tracker / хранилище

SQLite с одной основной таблицей `applications`, колонки — плоская проекция `ApplicationRecord`. Резюме хранится отдельно как `resume_profile.json` (при необходимости с FAISS-индексом по секциям, если профиль вырастет за пределы одного JSON — но для MVP простого JSON достаточно, векторный поиск здесь не критичен и его можно пропустить без потери охвата тем: MCP и tool-calling важнее, чем RAG, которого уже достаточно в Smart Housing Finder).

`query_tracker_stats` — это тот инструмент, который отвечает на вопросы вроде "сколько заявок за неделю", "средний score среди тех, кто прислал отказ за час", "доля go-решений, которые всё равно получили отказ" — то есть закрывает разрыв между "агент посчитал fit" и "агент подтверждает или опровергает свою же оценку по факту".

## Eval-слой

5–10 golden-кейсов — и здесь можно использовать не выдуманные вакансии, а реальные, которые уже разбирались в этом чате (GeneralMind, Manex AI, Lucid Labs, WaveSix) плюс пару explicit mismatch-кейсов (вакансия на совершенно другой стек или сеньорность), чтобы проверить, что агент не завышает score из вежливости.

Для каждого кейса фиксируется вручную ожидаемый `verdict` (go/maybe/no_go) и допустимый диапазон `score`. Метрика — простая: доля кейсов, где `verdict` агента совпал с golden-verdict (accuracy по трёхклассовой классификации), плюс средняя абсолютная разница score. LLM-as-judge поверх этого не обязателен — здесь есть объективный ground truth (сам автор), так что судья — это заранее сохранённые ответы, а не отдельная LLM-оценка. Promptfoo можно подключить как обвязку для прогона и визуализации, но самописный скрипт на 40 строк с pytest тоже полностью закрывает тему "eval-driven development" для портфолио.

## Структура репозитория

```
job-tracker-agent/
├── README.md
├── pyproject.toml
├── mcp_server/
│   ├── server.py              # регистрация tools
│   ├── tools/
│   │   ├── extraction.py
│   │   ├── scoring.py
│   │   └── tracker.py
│   └── schemas.py             # Pydantic-модели из раздела выше
├── agent/
│   ├── graph.py                # LangGraph узлы и рёбра
│   └── state.py
├── data/
│   ├── resume_profile.json
│   └── tracker.db
├── evals/
│   ├── golden_cases.yaml       # 5-10 кейсов с ожидаемым verdict/score
│   └── run_eval.py
└── cli.py
```

## План по дням (3–5 дней с Claude Code)

День 1: схемы данных (Pydantic), MCP-сервер со стабами инструментов, `resume_profile.json` под свой реальный профиль.

День 2: реализация `extract_job_requirements` и `compute_fit_score` (промпты + детерминированная часть скоринга), первый end-to-end прогон на одной реальной вакансии.

День 3: LangGraph граф целиком (все узлы, ветка `clarify`), SQLite-трекер, CLI для score/log/stats.

День 4: eval-набор на реальных вакансиях из этого чата, прогон, итерация на промптах по расхождениям с golden-verdict.

День 5: README с архитектурной схемой, полировка CLI-вывода, при желании — минимальный FastAPI-обёртка поверх графа для демо.

## Что должно попасть в README

Однострочная формулировка проблемы (реальная, личная — 45+ заявок за неделю, ручной разбор каждой), диаграмма архитектуры из этого документа, таблица MCP tools с примером вызова, пример golden-кейса из eval-набора с реальным score, и короткий блок "что бы я сделал дальше" (email-парсер для авто-обновления outcome, browser extension для one-click логирования прямо со страницы вакансии) — это стандартный сигнал на собеседовании, что проект не заброшен на первой рабочей версии.
