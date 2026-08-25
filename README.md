# AI Job Application Tracker Agent

Агент, который читает вакансию, извлекает требования через MCP tools, сравнивает их с профилем резюме, выдаёт fit-score с объяснением (go/no-go) и логирует решение в персистентный трекер заявок.

Полный технический scope — архитектура, контракты MCP tools, схемы данных, план по дням — в [`SPEC.md`](./SPEC.md).

## Статус

Это скелет проекта после дня 1: структура репозитория, Pydantic-схемы данных и MCP-сервер с зарегистрированными, но пока не реализованными инструментами (каждый вызывает `NotImplementedError` с указанием, что нужно дописать). Реальная логика извлечения/скоринга, LangGraph-граф, tracker DB и eval-набор — следующие шаги по плану из SPEC.md.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # заполнить ANTHROPIC_API_KEY
```

Заполни `data/resume_profile.json` своими реальными скиллами (сейчас там шаблон с плейсхолдерами) — от него зависит, насколько адекватным будет fit-score.

## Проверка, что MCP-сервер поднимается

```bash
python -m mcp_server.server
```

## Структура

```
job-tracker-agent/
├── SPEC.md                 # архитектура, контракты tools, план
├── mcp_server/
│   ├── server.py           # регистрация MCP tools (FastMCP)
│   ├── schemas.py          # Pydantic-модели
│   └── tools/
│       ├── extraction.py   # fetch_job_posting, extract_job_requirements
│       ├── scoring.py      # load_resume_profile, compute_fit_score
│       └── tracker.py      # log_application, update_application_outcome, query_tracker_stats
├── agent/
│   ├── state.py            # LangGraph state
│   └── graph.py            # узлы графа (заготовка)
├── data/
│   └── resume_profile.json # заполнить своими данными
└── evals/
    ├── golden_cases.yaml   # golden-кейсы для eval (заготовка)
    └── run_eval.py
```
