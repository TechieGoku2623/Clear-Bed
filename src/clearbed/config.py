"""Runtime configuration loaded from the environment and an optional .env file.

Paths and secrets stay here so the rest of the codebase never hard-codes them.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def repo_root() -> Path:
    """Return the repository root (two levels above this file)."""
    return Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """ClearBed settings.

    ``DATA_MODE=synthetic`` is the only mode that may call Groq. Real-data
    deployments must use a local model or Bedrock under a BAA.
    """

    model_config = SettingsConfigDict(
        env_file=str(repo_root() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    data_mode: Literal["synthetic", "real"] = "synthetic"
    environment: Literal["dev", "prod"] = "dev"
    log_level: str = "INFO"

    llm_provider: Literal["ollama", "bedrock", "groq", "mock"] = "ollama"
    ollama_model: str = "llama3.1"
    ollama_base_url: str = "http://localhost:11434"
    aws_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"

    hospital_zip: str = "02118"

    api_key: str = "demo-key"
    api_base_url: str = "http://localhost:8000"
    ui_origin: str = "http://localhost:8501"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    cost_per_bed_day: float = 2500.0
    census_size: int = 60
    rag_min_similarity: float = 0.25
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    cms_snf_url: str = (
        "https://data.cms.gov/provider-data/api/1/datastore/query/4pq5-n9py/0/download?format=csv"
    )
    synthea_population: int = 5000
    synthea_seed: int = 42

    project_root: Path = Field(default_factory=repo_root)
    warehouse_path: Path | None = None
    model_dir: Path | None = None
    chroma_dir: Path | None = None
    reports_dir: Path | None = None
    checkpoint_path: Path | None = None
    cms_snf_csv: Path | None = None
    data_raw_dir: Path | None = None
    data_external_dir: Path | None = None
    data_processed_dir: Path | None = None
    knowledge_dir: Path | None = None
    mlflow_dir: Path | None = None

    @field_validator("hospital_zip")
    @classmethod
    def _pad_zip(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if not digits:
            raise ValueError("HOSPITAL_ZIP must contain digits")
        return digits.zfill(5)[:5]

    def _pick(self, override: Path | None, *parts: str) -> Path:
        if override is not None:
            return override
        return self.project_root.joinpath(*parts)

    @property
    def raw_dir(self) -> Path:
        """Directory of untouched source extracts."""
        return self._pick(self.data_raw_dir, "data", "raw")

    @property
    def external_dir(self) -> Path:
        """Directory of third-party reference files such as the CMS extract."""
        return self._pick(self.data_external_dir, "data", "external")

    @property
    def processed_dir(self) -> Path:
        """Directory of intermediate files produced by ClearBed."""
        return self._pick(self.data_processed_dir, "data", "processed")

    @property
    def synthea_csv_dir(self) -> Path:
        """Synthea CSV export directory."""
        return self.raw_dir / "synthea" / "csv"

    @property
    def resolved_warehouse_path(self) -> Path:
        """DuckDB file used as the local warehouse."""
        return self._pick(self.warehouse_path, "data", "warehouse.duckdb")

    @property
    def resolved_model_dir(self) -> Path:
        """Directory where trained model artifacts are written."""
        return self._pick(self.model_dir, "models")

    @property
    def resolved_chroma_dir(self) -> Path:
        """Persistent Chroma directory for the placement knowledge base."""
        return self._pick(self.chroma_dir, "data", "chroma")

    @property
    def resolved_reports_dir(self) -> Path:
        """Directory for HTML, markdown, and plot reports."""
        return self._pick(self.reports_dir, "reports")

    @property
    def resolved_checkpoint_path(self) -> Path:
        """SQLite file used by the LangGraph checkpointer."""
        return self._pick(self.checkpoint_path, "data", "agent_checkpoints.sqlite")

    @property
    def resolved_cms_csv(self) -> Path:
        """Local CMS nursing-home CSV, downloaded when missing."""
        return self._pick(self.cms_snf_csv, "data", "external", "nh_provider_info.csv")

    @property
    def resolved_knowledge_dir(self) -> Path:
        """Curated markdown knowledge base."""
        return self._pick(self.knowledge_dir, "knowledge")

    @property
    def resolved_mlflow_dir(self) -> Path:
        """Local MLflow file store."""
        return self._pick(self.mlflow_dir, "mlruns")

    @property
    def mlflow_tracking_uri(self) -> str:
        """MLflow tracking URI pointing at the local file store."""
        return self.resolved_mlflow_dir.resolve().as_uri()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings object. Call ``cache_clear`` in tests."""
    return Settings()
