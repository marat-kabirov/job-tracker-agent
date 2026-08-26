# AI Job Application Tracker Agent

45+ applications a week, and for every posting you need to decide in a couple of minutes: is this even worth applying to? This agent reads a job posting, extracts its requirements, compares them against a resume profile, produces a fit-score with an explanation (go/maybe/no_go), and logs the decision to a tracker — automating the exact manual work you'd otherwise do by hand for every posting.

Full technical scope — MCP tool contracts, data schemas, the reasoning behind architectural decisions — lives in [`SPEC.md`](./SPEC.md).

## Architecture

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
                                  │ calls MCP tools along the way
                                  ▼
        ┌───────────────────────────────────────────────────────┐
        │              MCP Server (mcp_server/)                  │
        │                                                         │
        │  extract_job_requirements   Groq, structured output      │
        │  load_resume_profile        reads resume_profile.json    │
        │  compute_fit_score          hard-filters + skill match    │
        │                             + final LLM scoring           │
        │  log_application / update_application_outcome /           │
        │  query_tracker_stats        SQLite (SQLAlchemy)            │
        └───────────────────────────┬───────────────────────────┘
                                     ▼
              data/tracker.db (SQLite) + data/resume_profile.json
```

The `clarify` node is the branch for vague postings: if `extract_job_requirements` comes back with an empty `required_stack`, the graph doesn't try to guess a score — it asks for clarification and writes nothing to the tracker.

## MCP tools

| Tool | What it does |
|---|---|
| `extract_job_requirements` | Groq (`ChatGroq.with_structured_output`) parses raw posting text into `JobRequirements` — no manual regex/JSON parsing. Doesn't crash on vague text: honestly returns whatever it could extract. |
| `load_resume_profile` | Reads and validates `data/resume_profile.json` via `ResumeProfile`. |
| `compute_fit_score` | Two-tier scoring: deterministic hard-filters + two-phase skill matching + final LLM scoring. Details below. |
| `log_application` | Writes an application (posting + fit-score + decision) to SQLite, returns an `application_id` (uuid4). |
| `update_application_outcome` | Records the real-world outcome (`rejected` / `interview` / `ghosted` / `offer`) once a response comes in, via `cli.py update`. |
| `query_tracker_stats` | Tracker-wide aggregates: number of applications, average score by outcome, average time-to-rejection, share of `go`-decisions that still got rejected. |

## How the score is computed

Scoring isn't a single "gut feeling" LLM call — it's three layers, each with its own area of responsibility.

**1. Hard-filters (deterministic, no LLM).** These check facts, not judgment calls: a seniority gap (a rough read of candidate level from `years_experience_total` vs. the posting's stated `seniority_level`), remote mismatch, location mismatch, language mismatch, a conflict on `work_authorization` (a heuristic over phrases like *"no visa sponsorship"* in the posting's raw text). If even one filter fires, the final score is forced below the `maybe` threshold — **the LLM cannot override a fact**: if the resume plainly states a student visa with no sponsorship, and the posting plainly states "no sponsorship," the verdict physically cannot become `go`, no matter what the model decides in the next step.

**2. Two-phase skill matching.** Phase 1 is an exact-string, case-insensitive match between the posting's `required_stack` and the resume's skill names — cheap and reliable wherever the wording literally lines up. Phase 2 handles what didn't match (e.g. the posting asks for `"Next.js"`, and the resume has `"React"` and `"TypeScript"` but not the literal string `"Next.js"`): one extra Groq call with structured output decides whether the candidate's resume covers that need semantically, with a short justification. This isn't a hand-maintained alias table (which doesn't generalize to new posting vocabulary) — it's an LLM decision for exactly the case plain string matching can't resolve. Every semantic match is flagged separately and stated explicitly in the final `explanation`, so it never reads as if it were a direct match: "covered via adjacent experience, not direct use of the tool."

**3. Final LLM scoring on top of the facts.** The model receives the already-computed `matched_skills` / `missing_skills` / `hard_fail_reasons` / `semantic_match_notes` plus the full posting text, evaluates nice-to-have stack and implicit signals (red flags like "rockstar ninja," unrealistic requirements), and produces `score` (0–100), `explanation`, and `confidence`. `verdict` is derived from `score` by a threshold in code (`GO_THRESHOLD=70`, `MAYBE_THRESHOLD=50`), never asked from the LLM directly — the threshold stays the single place where `go`/`maybe`/`no_go` gets decided.

## Eval

Fit-scoring is validated against a golden dataset of 4 real job postings from this job search (GeneralMind, Manex AI, Lucid Labs, WaveSix), each with a verdict the author assigned manually before any agent existed. The agent currently reaches **3/4 (75%) verdict accuracy** against that dataset, with hard-filters enforced deterministically so the LLM can't override an explicit disqualifying fact.

Groq isn't strictly bit-for-bit deterministic even at `temperature=0`, so scores on borderline cases can shift slightly between runs.

**23 pytest tests** cover the pipeline: deterministic hard-filters and exact/semantic skill matching (mocked, no network), the SQLite tracker (temp DB, not `data/tracker.db`), LangGraph routing (mocked tools), and one live end-to-end pass against Groq (network-gated behind the `requires_groq` pytest marker).

```bash
pytest              # full suite
python evals/run_eval.py   # run the golden dataset with a report
```

## What I'd do next

- **Email parser for automatic outcome updates** — right now `update_application_outcome` is called manually via the CLI when a response arrives; an inbox parser would close that gap automatically.
- **Browser extension for one-click logging** — straight from a job posting's page, without copy-pasting text into a file.
- **URL ingestion** — fetch and clean a posting directly from a link instead of pasting text in.
- **Grow the golden dataset** — more real postings, covering a wider range of stacks and seniority levels.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env   # fill in GROQ_API_KEY (console.groq.com/keys, free tier)
```

Fill `data/resume_profile.json` with your real skills (instructions in `data/RESUME_PROFILE_INSTRUCTIONS.md`) — the `years`/`proficiency` fields directly determine how sensible the fit-score is: empty/zero values mean the seniority hard-filter will fire almost every time.

Default model is `openai/gpt-oss-120b` (see `mcp_server/tools/_llm.py`); override via `GROQ_MODEL` in `.env` if Groq's model lineup changes.

## Usage

```bash
python -m mcp_server.server                 # start the MCP server (stdio)

python cli.py score --file posting.txt      # run a posting through the agent
python cli.py stats [--since YYYY-MM-DD]    # tracker-wide aggregates
python cli.py update <application_id> <outcome>   # rejected/interview/ghosted/offer
```

## Repository structure

```
job-tracker-agent/
├── SPEC.md                        # architecture, tool contracts, day-by-day plan
├── README.md                      # this file
├── cli.py                         # Typer CLI: score / stats / update
├── agent/
│   ├── state.py                   # AgentState (TypedDict)
│   └── graph.py                   # graph nodes: ingest/extract/retrieve_profile/score/decide/log/clarify
├── mcp_server/
│   ├── server.py                  # registers the MCP tools
│   ├── schemas.py                 # Pydantic models (JobRequirements, ResumeProfile, FitScoreResult, ...)
│   └── tools/
│       ├── _llm.py                # shared helper — ChatGroq client
│       ├── extraction.py          # posting parsing via Groq (structured output)
│       ├── scoring.py             # load_resume_profile, compute_fit_score (hard-filters + skill match + LLM)
│       └── tracker.py             # log_application, update_application_outcome, query_tracker_stats
├── data/
│   ├── resume_profile.json        # fill in with your own data
│   ├── RESUME_PROFILE_INSTRUCTIONS.md
│   └── tracker.db                 # created automatically, not in git
├── evals/
│   ├── golden_cases.yaml          # 4 real job postings with manual verdict/score
│   └── run_eval.py                # run + report
└── tests/
    ├── conftest.py                # requires_groq marker, load_dotenv
    ├── test_scoring_deterministic.py   # hard-filters, exact/semantic skill match
    ├── test_pipeline_llm.py            # end-to-end raw_text -> JobRequirements -> FitScoreResult (real Groq)
    ├── test_tracker.py                 # SQLite tracker against a temp database
    └── test_graph_smoke.py             # LangGraph routing (tools mocked)
```
