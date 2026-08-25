"""Прогон golden_cases.yaml через агента и сравнение с ожидаемым verdict/score.

День 4 по плану (см. SPEC.md, "Eval-слой"). Метрика: accuracy по verdict
(трёхклассовая классификация go/maybe/no_go) + средняя абсолютная разница
score. Ground truth — заранее сохранённые ручные оценки, отдельный
LLM-as-judge не нужен (см. обоснование в SPEC.md).
"""

from __future__ import annotations

from pathlib import Path

import yaml

GOLDEN_CASES_PATH = Path(__file__).parent / "golden_cases.yaml"


def load_golden_cases() -> list[dict]:
    with open(GOLDEN_CASES_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("cases", [])


def run_eval() -> None:
    cases = load_golden_cases()
    if not cases:
        print(
            f"Нет кейсов в {GOLDEN_CASES_PATH} — заполни golden_cases.yaml "
            "реальными вакансиями перед прогоном (см. TODO там же)."
        )
        return

    # TODO (день 4):
    #   1. для каждого кейса прогнать case["job_text"] через agent.graph
    #   2. сравнить fit.verdict с case["expected_verdict"]
    #   3. проверить fit.score в диапазоне case["expected_score_range"]
    #   4. посчитать accuracy по verdict + mean absolute error по score
    #   5. напечатать отчёт: какие кейсы разошлись и как именно
    raise NotImplementedError("TODO день 4: run_eval")


if __name__ == "__main__":
    run_eval()
