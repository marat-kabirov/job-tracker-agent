# AI Job Application Tracker Agent

45+ заявок в неделю, и по каждой вакансии нужно за пару минут понять: стоит ли вообще подавать. Этот агент читает текст вакансии, извлекает требования, сравнивает их с профилем резюме, выдаёт fit-score с объяснением (go/maybe/no_go) и логирует решение в трекер — то есть автоматизирует ровно ту ручную работу, которую иначе делаешь сам при каждом разборе вакансии.

Полный технический scope — контракты MCP tools, схемы данных, обоснование архитектурных решений — в [`SPEC.md`](./SPEC.md). Этот README — про то, что реально получилось после дней 1–4: рабочий MCP-сервер, LangGraph-агент, SQLite-трекер, CLI и eval-набор на 4 реальных вакансиях.

## Статус

Проект рабочий целиком, с одним честным исключением: `fetch_job_posting` (скачивание вакансии по URL) не реализован — на вход агент принимает только текст вакансии, вставленный вручную. Это сознательный вырез из MVP (см. SPEC.md), не забытая доработка.

Всё остальное — извлечение требований через Groq, скоринг, LangGraph-граф, SQLite-трекер, CLI, eval — реализовано и покрыто тестами (23 pytest-теста, подробности в разделе [Eval](#eval-датасет-первый-прогон-фиксы-и-честная-цифра-в-конце)).

## Архитектура

```
                 python cli.py score --file posting.txt
                 python cli.py stats / update <id> <outcome>
                              │
                              ▼
              ┌─────────────────────────────────────┐
              │   LangGraph agent (agent/graph.py)    │
              │                                        │
              │  ingest → extract ─┬→ retrieve_profile │
              │                    │        │          │
              │                    │        ▼          │
              │              (low confidence) score     │
              │                    │        │          │
              │                    ▼        ▼          │
              │                clarify    decide → log │
              └───────────────────┬────────────────────┘
                                  │ вызывает MCP tools по ходу графа
                                  ▼
        ┌───────────────────────────────────────────────────────┐
        │              MCP Server (mcp_server/)                  │
        │                                                         │
        │  fetch_job_posting          ❌ не реализован             │
        │  extract_job_requirements   Groq, structured output      │
        │  load_resume_profile        читает resume_profile.json   │
        │  compute_fit_score          hard-filters + skill match    │
        │                             + финальный LLM-скоринг       │
        │  log_application / update_application_outcome /           │
        │  query_tracker_stats        SQLite (SQLAlchemy)            │
        └───────────────────────────┬───────────────────────────┘
                                     ▼
              data/tracker.db (SQLite) + data/resume_profile.json
```

Узел `clarify` — ветка для расплывчатых вакансий: если `extract_job_requirements` вернул пустой `required_stack`, граф не пытается угадать score, а просит уточнение и не пишет ничего в трекер.

## MCP tools

| Tool | Статус | Что делает |
|---|---|---|
| `fetch_job_posting` | ❌ **Не реализован** (`NotImplementedError`) | Должен был скачивать вакансию по URL и чистить HTML до текста. Сознательно вырезан из MVP — агент принимает только готовый текст вакансии. |
| `extract_job_requirements` | ✅ | Groq (`ChatGroq.with_structured_output`) парсит сырой текст вакансии в `JobRequirements` — без ручного regex/JSON-парсинга. Не падает на расплывчатом тексте: честно возвращает то, что смог извлечь (в т.ч. пустой `required_stack`). |
| `load_resume_profile` | ✅ | Читает и валидирует `data/resume_profile.json` через `ResumeProfile`. |
| `compute_fit_score` | ✅ | Двухуровневый скоринг: детерминированные hard-filters + двухфазный skill-матчинг + финальный LLM-скоринг. Подробности — в разделе [Как считается score](#как-считается-score). |
| `log_application` | ✅ | Пишет заявку (вакансия + fit-score + decision) в SQLite, возвращает `application_id` (uuid4). |
| `update_application_outcome` | ✅ | Проставляет реальный исход (`rejected` / `interview` / `ghosted` / `offer`), когда приходит ответ — вручную через `cli.py update`. |
| `query_tracker_stats` | ✅ | Агрегаты по трекеру: сколько заявок, средний score по исходам, среднее время до отказа, доля `go`-решений, всё равно получивших отказ. |

## Как считается score

Скоринг — не один LLM-вызов «на глаз», а три слоя, каждый со своей зоной ответственности.

**1. Hard-filters (детерминированные, без LLM).** Проверяются факты, а не суждения: разрыв по seniority (грубая оценка уровня кандидата по `years_experience_total` vs заявленный `seniority_level` вакансии), remote-mismatch, location-mismatch, language-mismatch, конфликт по `work_authorization` (эвристика по фразам вроде *"no visa sponsorship"* в сыром тексте вакансии). Если сработал хотя бы один фильтр, итоговый score принудительно капается ниже порога `maybe` — **LLM не может переопределить факт**: если резюме прямо говорит про студенческую визу без спонсорства, а вакансия прямо пишет "no sponsorship", verdict физически не может стать `go`, независимо от того, что решит модель на следующем шаге.

**2. Skill-matching, в две фазы.** Фаза 1 — exact-string case-insensitive матч между `required_stack` вакансии и именами скиллов в резюме: дёшево и надёжно там, где формулировки буквально совпадают. Фаза 2 — для того, что не совпало (например, вакансия просит `"Next.js"`, а в резюме есть `"React"` и `"TypeScript"`, но не `"Next.js"` буквально), один дополнительный Groq-вызов со structured output решает, покрывает ли резюме кандидата эту потребность семантически, и даёт короткое обоснование. Это не ручная alias-таблица (не масштабируется на новую лексику вакансий) — это LLM-решение того, что не решается точным совпадением строк. Каждый semantic-матч помечается отдельно и явно проговаривается в итоговом `explanation`, чтобы не выглядело как обман: "покрыт через смежный опыт, а не прямое использование инструмента".

**3. Финальный LLM-скоринг поверх фактов.** Модель получает уже посчитанные `matched_skills` / `missing_skills` / `hard_fail_reasons` / `semantic_match_notes` и текст вакансии целиком, оценивает nice-to-have стек и неявные сигналы (red flags вроде "rockstar ninja", нереалистичные требования) и выдаёт `score` (0–100), `explanation` и `confidence`. `verdict` считается из `score` по порогу в коде (`GO_THRESHOLD=70`, `MAYBE_THRESHOLD=50`), а не запрашивается у LLM напрямую — порог остаётся единственным местом, где решается `go`/`maybe`/`no_go`.

## Eval: датасет, первый прогон, фиксы — и честная цифра в конце

Golden-датасет — 4 реальные вакансии из этого же job-серча (GeneralMind, Manex AI, Lucid Labs, WaveSix), не выдуманные кейсы: для каждой в `evals/golden_cases.yaml` зафиксирован ручной вердикт (`go`/`maybe`/`no_go`) и ожидаемый диапазон score, сделанный автором на момент реального разбора этой вакансии, до всякого агента.

**Первый прогон: 2/4 (50%) verdict accuracy.** Root cause у всех расхождений был один и тот же: exact-string keyword matching не видел семантически эквивалентные, но по-разному написанные формулировки — вакансия просит `"Next.js"`/`"vector databases"`, резюме содержит `"React"+"TypeScript"`/`"FAISS / vector search"`. Строки не совпадали, значит навык считался отсутствующим, и заниженный `stack_score` тянул вниз весь итоговый score.

**Фикс 1 — двухфазный semantic skill-матчинг.** Механизм заработал буквально: покрытие стека заметно выросло (WaveSix — 22% → 78–88%, GeneralMind — 0% → 33%, оба с конкретными, проверяемыми обоснованиями от модели). Но accuracy осталась на месте — 2/4. Это вскрыло вторую, независимую проблему: WaveSix теперь имел почти полное покрытие стека, но всё равно не дотягивал до `go`, потому что финальный LLM-шаг сам, по собственной инициативе, штрафовал за низкий `years_experience_total`, даже когда сама вакансия вообще не требовала конкретного стажа.

**Фикс 2 — устранён задвоенный штраф за опыт.** Разрыв по реально заявленному стажу (например, Lucid Labs прямо пишет *"3+ years professional experience"*) и так ловится детерминированным hard-filter'ом на seniority. Финальный LLM-скоринг не должен был штрафовать за годы опыта второй раз, тем более когда вакансия вообще не указывает требования к стажу. После фикса — **verdict accuracy выросла до 3/4 (75%)**: WaveSix сдвинулся с `maybe`(~55) на `go`(70), попав в ожидаемый диапазон.

**Один оставшийся known limitation — GeneralMind.** Модель не выводит culture-fit из совпадения формулировок: human-разметка отмечала fit через дословную перекличку ("automation mindset" в вакансии и в резюме кандидата), а не через стек. Это осознанное ограничение, а не баг — учить модель ловить текстовые переклички как сигнал fit означало бы переобучаться под один конкретный пример вместо общего принципа. Задокументировано в `_KNOWN_MISMATCH_NOTES` в `evals/run_eval.py`.

Отдельно стоит сказать про воспроизводимость: Groq не гарантирует бит-в-бит детерминизм даже при `temperature=0`, поэтому один из кейсов (Manex AI) наблюдался и как `MATCH`, и как `MISMATCH` на одном и том же входе в разных прогонах — это задокументировано как известное ограничение eval'а на 4 кейсах, а не как нестабильность, которую нужно скрывать.

**Тесты: 23 pytest-теста.** Часть — сетевые, реально бьют по Groq (помечены маркером `requires_groq` из `tests/conftest.py`, пропускаются автоматически, если `GROQ_API_KEY` не задан, а не падают): end-to-end путь `raw_text → JobRequirements → FitScoreResult` и один тест конкретно на semantic skill-матч (`"Next.js"` vs `"React"+"TypeScript"`). Остальные — детерминированные: hard-filters и exact-match логика проверяются без сети (semantic-матч замокан автоматически через `monkeypatch`), tracker-тесты гоняются на временной SQLite-базе (не на `data/tracker.db`), а end-to-end тест графа мокает все четыре tool-вызова, чтобы проверять только роутинг узлов, не LLM.

```bash
pytest              # весь набор
python evals/run_eval.py   # прогон golden-датасета с отчётом
```

## Что бы я сделал дальше

- **Email-парсер для авто-обновления outcome** — сейчас `update_application_outcome` вызывается вручную через CLI, когда приходит ответ; парсер входящих писем закрыл бы этот разрыв автоматически.
- **Browser extension для one-click логирования** — прямо со страницы вакансии, без copy-paste текста в файл.
- **Расширить golden-датасет за пределы 4 кейсов** — добавить больше explicit no-match вакансий (другой стек, другой seniority), чтобы eval не был настолько чувствителен к одному пограничному кейсу (см. Manex AI выше) и метрика точнее отражала реальное поведение на новых вакансиях.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env   # заполнить GROQ_API_KEY (console.groq.com/keys, бесплатный тариф)
```

Заполни `data/resume_profile.json` своими реальными скиллами (инструкция — `data/RESUME_PROFILE_INSTRUCTIONS.md`) — от `years`/`proficiency` там напрямую зависит, насколько адекватным будет fit-score: пустые/нулевые значения означают, что hard-filter по seniority сработает почти всегда.

Модель по умолчанию — `openai/gpt-oss-120b` (см. `mcp_server/tools/_llm.py`); переопределяется через `GROQ_MODEL` в `.env`, если список моделей Groq изменится.

## Использование

```bash
python -m mcp_server.server                 # поднять MCP-сервер (stdio)

python cli.py score --file posting.txt      # прогнать вакансию через агента
python cli.py stats [--since YYYY-MM-DD]    # агрегаты по трекеру
python cli.py update <application_id> <outcome>   # rejected/interview/ghosted/offer
```

## Структура репозитория

```
job-tracker-agent/
├── SPEC.md                        # архитектура, контракты tools, план по дням
├── README.md                      # этот файл
├── cli.py                         # Typer CLI: score / stats / update
├── agent/
│   ├── state.py                   # AgentState (TypedDict)
│   └── graph.py                   # узлы графа: ingest/extract/retrieve_profile/score/decide/log/clarify
├── mcp_server/
│   ├── server.py                  # регистрация 7 MCP tools
│   ├── schemas.py                 # Pydantic-модели (JobRequirements, ResumeProfile, FitScoreResult, ...)
│   └── tools/
│       ├── _llm.py                # общий helper — ChatGroq клиент
│       ├── extraction.py          # fetch_job_posting (❌), extract_job_requirements
│       ├── scoring.py             # load_resume_profile, compute_fit_score (hard-filters + skill match + LLM)
│       └── tracker.py             # log_application, update_application_outcome, query_tracker_stats
├── data/
│   ├── resume_profile.json        # заполнить своими данными
│   ├── RESUME_PROFILE_INSTRUCTIONS.md
│   └── tracker.db                 # создаётся автоматически, не в git
├── evals/
│   ├── golden_cases.yaml          # 4 реальные вакансии с ручным verdict/score
│   └── run_eval.py                # прогон + отчёт + _KNOWN_MISMATCH_NOTES
└── tests/
    ├── conftest.py                # requires_groq marker, load_dotenv
    ├── test_scoring_deterministic.py   # hard-filters, exact/semantic skill match
    ├── test_pipeline_llm.py            # end-to-end raw_text -> JobRequirements -> FitScoreResult (реальный Groq)
    ├── test_tracker.py                 # SQLite tracker на временной базе
    └── test_graph_smoke.py             # роутинг LangGraph-графа (tools замокан)
```
