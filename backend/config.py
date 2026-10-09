# backend/config.py
import os
import sys
from pathlib import Path
import platformdirs
from pydantic_settings import BaseSettings, SettingsConfigDict

# Modo offline estricto
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"


def get_base_dir() -> Path:
    """Retorna la ruta base de la aplicación tanto en desarrollo como empaquetada."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    GEMINI_API_KEY: str
    GEMINI_MODEL_SYNTHESIS: str = "gemini-2.5-flash"
    GEMINI_MODEL_REWRITE: str = "gemini-2.0-flash-lite"

    @property
    def GEMINI_MODEL(self) -> str:
        return self.GEMINI_MODEL_SYNTHESIS

    # Nombres de identificador
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    SPARSE_MODEL_NAME: str = "Qdrant/bm25"
    RERANKER_MODEL_NAME: str = "BAAI/bge-reranker-base"

    APP_NAME: str = "CopilotoNormativas"
    APP_AUTHOR: str = "ArquitecturaSistemas"
    QDRANT_COLLECTION_NAME: str = "normativas_tecnicas"
    CARPETA_VIGENCIA: str = "2025-2026"

    model_config = SettingsConfigDict(
        env_file=get_base_dir() / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def data_dir(self) -> Path:
        """Ruta en AppData (Windows) o Application Support (macOS)."""
        path = Path(platformdirs.user_data_dir(self.APP_NAME, self.APP_AUTHOR))
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def qdrant_path(self) -> Path:
        """Ruta local donde Qdrant persistirá los vectores en disco."""
        path = self.data_dir / "qdrant_db"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def sqlite_path(self) -> Path:
        """Ruta del archivo SQLite para tracking de hashes y metadatos."""
        return self.data_dir / "normativas_metadata.db"

    @property
    def sqlite_url(self) -> str:
        """URL de conexión para SQLAlchemy."""
        return f"sqlite:///{self.sqlite_path}"

    # Rutas físicas a los modelos empaquetados
    @property
    def models_cache_dir(self) -> Path:
        return get_base_dir() / "models_cache"

    @property
    def dense_model_path(self) -> Path:
        return self.models_cache_dir / "bge-m3"

    @property
    def fastembed_cache_dir(self) -> Path:
        return self.models_cache_dir / "fastembed_cache"


try:
    settings = Settings()
except Exception as e:
    print(f"[ERROR DE CONFIGURACIÓN] Faltan variables en el archivo .env: {e}")
    settings = None