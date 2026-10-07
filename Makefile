.PHONY: setup lint test data dbt data-quality train score kb api ui eval all dbt-fixture ci format

export PYTHONPATH := src
UV := uv run
WAREHOUSE ?= $(CURDIR)/data/warehouse.duckdb
export CLEARBED_WAREHOUSE := $(WAREHOUSE)
export WAREHOUSE_PATH := $(WAREHOUSE)

setup:
	uv sync --all-groups

format:
	uv run ruff format src tests app
	uv run ruff check --fix src tests app

lint:
	uv run ruff check src tests app
	uv run ruff format --check src tests app
	uv run mypy src tests app

test:
	uv run pytest

data:
	bash scripts/get_synthea.sh
	bash scripts/generate_synthea.sh
	$(UV) python -m clearbed.ingest.synthea_loader
	$(UV) python -m clearbed.ingest.cms_snf_loader

dbt:
	CLEARBED_WAREHOUSE="$(WAREHOUSE)" PYTHONPATH=src $(UV) dbt build --project-dir dbt --profiles-dir dbt

dbt-fixture:
	CLEARBED_WAREHOUSE="$(CURDIR)/data/fixture_warehouse.duckdb" WAREHOUSE_PATH="$(CURDIR)/data/fixture_warehouse.duckdb" $(UV) python -m clearbed.ingest.fixture_loader
	CLEARBED_WAREHOUSE="$(CURDIR)/data/fixture_warehouse.duckdb" WAREHOUSE_PATH="$(CURDIR)/data/fixture_warehouse.duckdb" PYTHONPATH=src $(UV) dbt build --project-dir dbt --profiles-dir dbt

data-quality:
	$(UV) python -m clearbed.features.quality_report

train:
	$(UV) python -m clearbed.ml.train

score:
	$(UV) python -m clearbed.ml.score

kb:
	$(UV) python -m clearbed.rag.ingest_kb

api:
	$(UV) uvicorn clearbed.api.main:app --host 0.0.0.0 --port 8000

ui:
	$(UV) streamlit run app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0

eval:
	DATA_MODE=synthetic LLM_PROVIDER=mock $(UV) python -m clearbed.eval.eval_agent

ci: lint test dbt-fixture eval

all: data dbt data-quality train score kb
