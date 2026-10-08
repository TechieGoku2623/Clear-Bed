# Engineering conventions

ClearBed is a discharge-barrier prediction and placement copilot for hospital case managers.

## Stack

- Python 3.11, uv, ruff, mypy, pytest
- DuckDB as the local warehouse, with dbt-core and dbt-duckdb
- LightGBM, scikit-learn, SHAP, and a local MLflow file store
- LangGraph, LangChain, ChromaDB, and sentence-transformers (`all-MiniLM-L6-v2`)
- LLM access through a provider abstraction: `ollama` (default, local), `bedrock`, or `groq`
- FastAPI, Streamlit, and Docker Compose

## Rules

- Patient rows are synthetic (Synthea) unless configuration says otherwise. Do not log full patient records.
- The Groq provider refuses to run when `DATA_MODE` is not `synthetic`. Real data stays on `bedrock` or `ollama`.
- Configuration lives in `src/clearbed/config.py`. Paths and keys are not hard-coded.
- Modules carry type hints, docstrings, and at least one pytest.
- Any action that leaves the system, including sending a referral, waits for a person to approve it.
- Keep functions small. Notebooks stay out of `src/`.
- When an external file's headers are uncertain, inspect and map them instead of assuming column names.
- Update `README.md` when a new command is added.
