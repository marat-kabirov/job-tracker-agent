"""Прогон golden_cases.yaml через агента и сравнение с ожидаемым verdict/score.

День 4 по плану (см. SPEC.md, "Eval-слой"). Метрики: verdict accuracy
(трёхклассовая классификация go/maybe/no_go) и score-in-range rate — доля
кейсов, где итоговый score попал в вручную зафиксированный expected_score_range.
Ground truth — заранее сохранённые ручные оценки автора (сам факт того, что
вакансия была реально просмотрена и по ней принято решение подать/не подать),
отдельный LLM-as-judge не нужен (см. обоснование в SPEC.md).

Датасет — всего 4 реальных кейса. Оверфитить пороги/промпты под 4 точки —
плохая идея (легко "нарисовать" 4/4 и получить нерепрезентативную модель
поведения на новых вакансиях), поэтому расхождения здесь фиксируются как есть,
без подгонки. См. _KNOWN_MISMATCH_NOTES ниже, если после прогона появляются
устойчивые объяснения конкретных расхождений.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

# Windows-консоль по умолчанию открывает stdout в cp1252/cp866 и падает на
# юникод-символах (тире, кавычки) из LLM-объяснений — переключаем на utf-8.
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent.graph import build_graph  # noqa: E402

GOLDEN_CASES_PATH = Path(__file__).parent / "golden_cases.yaml"

# Сколько символов explanation показывать в построчном отчёте — достаточно,
# чтобы увидеть ход рассуждения модели, не заваливая терминал полным текстом.
EXPLANATION_PREVIEW_LEN = 150

# Известные расхождения между golden-разметкой и текущим пайплайном, вместе
# с гипотезой о причине. Это НЕ повод подгонять пороги/промпты под 4 точки,
# а честная запись найденной причины.
#
# История фиксов (обе — генерализуемые фиксы дизайна, не подгонка под кейсы):
#   1) Семантический gap в skill-матчинге: _deterministic_match в scoring.py
#      стал двухфазным (exact-string match + LLM-based semantic match для
#      required_stack items, не совпавших по строке — см.
#      _semantic_skill_match). Было: extract_job_requirements извлекает
#      required_stack буквальными формулировками вакансии ("Next.js",
#      "vector databases"), а resume_profile.json хранит смежные, но не
#      идентичные по написанию названия ("React"+"TypeScript",
#      "FAISS / vector search") — exact match их не видел. 2/4 -> 2/4
#      accuracy (то же число, но по другой причине — semantic match честно
#      закрыл словарный разрыв, остались два независимых источника
#      расхождения, не связанных с keyword-матчингом).
#   2) Задвоенный штраф за опыт в финальном LLM-скоринге: _SCORE_SYSTEM_PROMPT
#      в _run_llm_assessment явно просил модель учитывать "неявные сигналы",
#      и модель по своей инициативе понижала score за низкий
#      years_experience_total, даже когда вакансия вообще не требовала
#      конкретного стажа (wavesix, generalmind) — при том что разрыв по
#      реально заявленному стажу/уровню (lucid_labs: "3+ years") уже ловится
#      детерминированным hard-filter на seniority. Промпт теперь явно
#      запрещает LLM-шагу штрафовать за years_experience_total отдельно —
#      это зона ответственности hard_fail_reasons, не финальной оценки.
#      2/4 -> 3/4 accuracy (wavesix: maybe(~55-58) -> go(~70), в диапазон).
#
# Остаются два случая, которые фикс (2) сознательно не адресует:
_KNOWN_MISMATCH_NOTES: dict[str, str] = {
    "generalmind": (
        "required_stack=['Claude Code','Next.js','Vercel']: 'Next.js' "
        "матчится semantic'ом через React/TypeScript (stack_score 0.0 -> "
        "0.33), но 'Claude Code' и 'Vercel' остаются missing — semantic "
        "match вернул covered=False, и это похоже на правду: в резюме "
        "буквально нет опыта с этими инструментами. Разрыв с "
        "human-разметкой (verdict=go) не про стек и не про опыт: golden-кейс "
        "отмечал fit через soft-сигналы в тексте вакансии ('automation "
        "mindset', дословные формулировки), совпадающие с формулировками "
        "самого кандидата. Soft signal underweighted, by design — model "
        "correctly avoids inferring culture fit from phrasing overlap "
        "alone. Это честный known limitation, не баг: заставлять модель "
        "ловить дословные текстовые переклички как сигнал fit значило бы "
        "оптимизировать под один конкретный кейс, а не под общий принцип."
    ),
    "manex_ai": (
        "Нестабилен между прогонами на одном и том же тексте (наблюдались и "
        "MATCH~72-78, и MISMATCH~32-34) — Groq не гарантирует бит-в-бит "
        "детерминизм даже при temperature=0, и required_stack extraction "
        "иногда вытаскивает только 2 пункта (суть роли — agent workflows/"
        "MCP — сформулирована как компетенции, а не конкретные технологии, "
        "и не всегда попадает в required_stack). Стоит присматривать за "
        "этим кейсом при будущих прогонах eval."
    ),
    "wavesix": (
        "РЕШЕНО фиксом (2): раньше финальный LLM-scoring-шаг понижал score "
        "из-за years_experience_total=0.5, хотя вакансия вообще не требует "
        "конкретного стажа — задвоенный штраф поверх того, что hard-filter "
        "и так не сработал (seniority gap здесь недостаточно велик, чтобы "
        "быть hard-fail). После фикса: stack_score ~0.78-0.88 (semantic "
        "match закрыл 'LLM APIs'/'embeddings'/'vector databases'/"
        "'workflow automation'/'orchestration' через LangChain/FAISS/"
        "LangGraph), verdict — go(~70), в ожидаемом диапазоне. Оставлено "
        "здесь как запись истории, а не как открытое расхождение."
    ),
}
# lucid_labs (не в словаре выше, т.к. verdict совпадает — MATCH): score иногда
# выходит за верхнюю границу узкого expected_score_range ([0, 35], напр.
# фактический ~38-44) — тот же побочный эффект semantic match, что и у
# wavesix (LLM engineering/AI agents/model selection частично матчатся
# семантически, поднимая stack_score), но verdict остаётся корректным no_go,
# потому что hard-filter по seniority ("3+ years professional experience")
# всё равно срабатывает и капает score ниже MAYBE_THRESHOLD. Не трогалось
# специально — не наш кейс для этого фикса, задокументировано как есть.


def load_golden_cases() -> list[dict]:
    with open(GOLDEN_CASES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("cases", [])


def _run_case(graph, case: dict) -> dict:
    initial_state = {"raw_input": case["job_text"], "is_url": False}
    result = graph.invoke(initial_state)

    if result.get("needs_clarification") or "fit" not in result:
        return {
            "id": case["id"],
            "inconclusive": True,
            "clarification_reason": result.get("clarification_reason"),
        }

    fit = result["fit"]
    expected_verdict = case["expected_verdict"]
    expected_range = case["expected_score_range"]

    return {
        "id": case["id"],
        "inconclusive": False,
        "expected_verdict": expected_verdict,
        "actual_verdict": fit.verdict.value,
        "verdict_match": fit.verdict.value == expected_verdict,
        "expected_range": expected_range,
        "actual_score": fit.score,
        "score_in_range": expected_range[0] <= fit.score <= expected_range[1],
        "explanation": fit.explanation,
    }


def run_eval() -> None:
    cases = load_golden_cases()
    if not cases:
        print(
            f"Нет кейсов в {GOLDEN_CASES_PATH} — заполни golden_cases.yaml "
            "реальными вакансиями перед прогоном (см. TODO там же)."
        )
        return

    # Eval не должен трогать реальный data/tracker.db (log-узел графа вызывает
    # log_application) — на время прогона подменяем TRACKER_DB_PATH на файл
    # во временной директории и восстанавливаем исходное значение после.
    # Удаление — best-effort (ignore_errors), не через `with
    # TemporaryDirectory()`: tracker.py (день 3, не трогаем) открывает
    # SQLAlchemy engine на каждый вызов и не вызывает engine.dispose(), из-за
    # чего на Windows файл базы остаётся залочен ещё некоторое время после
    # последнего вызова, и обычное удаление временной директории падает с
    # PermissionError сразу после последнего log_application.
    original_db_path = os.environ.get("TRACKER_DB_PATH")
    tmp_dir = tempfile.mkdtemp(prefix="job_tracker_eval_")
    try:
        os.environ["TRACKER_DB_PATH"] = str(Path(tmp_dir) / "eval_tracker.db")
        graph = build_graph().compile()
        results = [_run_case(graph, case) for case in cases]
    finally:
        if original_db_path is None:
            os.environ.pop("TRACKER_DB_PATH", None)
        else:
            os.environ["TRACKER_DB_PATH"] = original_db_path
        shutil.rmtree(tmp_dir, ignore_errors=True)

    _print_report(results)


def _print_report(results: list[dict]) -> None:
    conclusive = [r for r in results if not r["inconclusive"]]
    inconclusive = [r for r in results if r["inconclusive"]]

    print("=" * 78)
    print("Eval report — golden_cases.yaml")
    print("=" * 78)

    for r in conclusive:
        status = "MATCH" if r["verdict_match"] else "MISMATCH"
        range_status = "in range" if r["score_in_range"] else "OUT OF RANGE"
        explanation_preview = (r["explanation"] or "").replace("\n", " ")[:EXPLANATION_PREVIEW_LEN]

        print(f"[{status}] {r['id']}")
        print(f"    verdict: expected={r['expected_verdict']!r:<8} actual={r['actual_verdict']!r}")
        print(
            f"    score:   expected_range={r['expected_range']}  "
            f"actual={r['actual_score']}  ({range_status})"
        )
        print(f"    explanation: {explanation_preview}...")

        note = _KNOWN_MISMATCH_NOTES.get(r["id"])
        if not r["verdict_match"] and note:
            print(f"    known mismatch note: {note}")

        print()

    if conclusive:
        verdict_matches = sum(r["verdict_match"] for r in conclusive)
        score_in_range_matches = sum(r["score_in_range"] for r in conclusive)
        print(
            f"Verdict accuracy:    {verdict_matches}/{len(conclusive)} "
            f"({verdict_matches / len(conclusive):.0%})"
        )
        print(
            f"Score-in-range rate: {score_in_range_matches}/{len(conclusive)} "
            f"({score_in_range_matches / len(conclusive):.0%})"
        )
    else:
        print("Нет кейсов с однозначным результатом — все ушли в clarify.")

    if inconclusive:
        print()
        print(f"Inconclusive (ушли в ветку clarify, verdict/score не сравнивались), {len(inconclusive)}:")
        for r in inconclusive:
            print(f"  - {r['id']}: {r['clarification_reason']}")


if __name__ == "__main__":
    run_eval()
