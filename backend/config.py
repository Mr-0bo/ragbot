# backend/config.py
import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_base_dir() -> Path:
    """Retorna la ruta base del proyecto (raíz del servidor)."""
    return Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # LLM Engine Selector: "local" (Gemma vía Ollama/llama.cpp) o "gemini"
    LLM_PROVIDER: str = "local"
    LOCAL_LLM_URL: str = "http://127.0.0.1:11434/v1"
    LOCAL_LLM_MODEL: str = "gemma2:2b"

    # Gemini (opcional para ejecución 100% offline)
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL_SYNTHESIS: str = "gemini-2.5-flash"
    GEMINI_MODEL_REWRITE: str = "gemini-2.5-flash"

    @property
    def GEMINI_MODEL(self) -> str:
        return self.GEMINI_MODEL_SYNTHESIS

    # Modelos de Inferencia Local
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    RERANKER_MODEL_NAME: str = "BAAI/bge-reranker-v2-m3"

    # Parámetros de Recuperación y Fusión
    TOP_K_PREFETCH: int = 20
    TOP_K_RERANK: int = 6

    APP_NAME: str = "CopilotoNormativasServer"
    QDRANT_COLLECTION_NAME: str = "normativas_tecnicas_hibridas"
    CARPETA_VIGENCIA: str = "2025-2026"

    # Ruta configurable por .env para el repositorio centralizado
    DIRECTORIO_DOCUMENTOS: str = str(get_base_dir() / "server_data" / "documentos_normativos")

    model_config = SettingsConfigDict(
        env_file=get_base_dir() / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def data_dir(self) -> Path:
        """Ruta local en el servidor donde persistirán bases de datos."""
        path = get_base_dir() / "server_data"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def qdrant_path(self) -> Path:
        """Ruta local donde Qdrant persistirá colecciones e índices en disco."""
        path = self.data_dir / "qdrant_db"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def sqlite_path(self) -> Path:
        """Ruta del archivo SQLite para historiales, usuarios y metadatos."""
        return self.data_dir / "normativas_server.db"

    @property
    def sqlite_url(self) -> str:
        """URL de conexión para SQLAlchemy."""
        return f"sqlite:///{self.sqlite_path}"

    @property
    def models_cache_dir(self) -> Path:
        """Directorio base para modelos cacheados."""
        path = get_base_dir() / "models_cache"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def dense_model_path(self) -> Path:
        return self.models_cache_dir / "bge-m3"

    @property
    def reranker_model_path(self) -> Path:
        return self.models_cache_dir / "bge-reranker-v2-m3"


try:
    settings = Settings()
except Exception as e:
    print(f"[ERROR DE CONFIGURACIÓN] Faltan variables en el archivo .env: {e}")
    settings = None