# Как заполнить resume_profile.json

Список `skills` уже предзаполнен твоим стеком из прошлого обсуждения (Python/FastAPI/Django/SQLAlchemy, TypeScript/React, LangChain/LangGraph, RAG, FAISS) — но `years` и `proficiency` у всех сейчас одинаковые заглушки (`0` и `"mid"`). От этих чисел напрямую зависит качество fit-score (день 2, `compute_fit_score`), так что перед тем как гонять реальные вакансии, стоит:

1. Проставить реальные `years` и `proficiency` (`junior`/`mid`/`senior`) для каждого скилла — можно удалить те, которыми не пользуешься, и добавить недостающие (Groq/Llama, KG-related стек, ETL — то, что было в трёх других pet-проектах).
2. Заполнить `years_experience_total` реальным числом.
3. Заменить все поля с `"TODO: ..."` на реальные значения — `languages`, `work_authorization`, `preferred_location`, `past_roles`.
4. Проверить `remote_preference` — сейчас стоит нейтральное `"hybrid_ok"`, поменять на `"remote_only"` или `"onsite_ok"`, если это не так.

Файл должен оставаться валидным JSON и проходить валидацию `ResumeProfile` из `mcp_server/schemas.py` — так и было проверено при сборке скелета (см. task "Проверить, что всё импортируется и запускается").
