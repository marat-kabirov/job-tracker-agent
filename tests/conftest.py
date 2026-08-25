from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

load_dotenv()

requires_groq = pytest.mark.skipif(
    not os.environ.get("GROQ_API_KEY"),
    reason="GROQ_API_KEY не задан в окружении/.env — пропускаем тесты с реальным вызовом Groq",
)
