import os
import sys
from pathlib import Path
import platformdirs
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_base_dir() -> Path:
    """Retorna la ruta base de la aplicación tanto en desarrollo como empaquetada."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # API Key de Gemini
    GEMINI_API_KEY: str

    # Modelo para síntesis documental y citas normativas estrictas
    GEMINI_MODEL_SYNTHESIS: str = "gemini-3.5-flash-lite"

    # Modelo para reformulación y descomposición de subconsultas
    GEMINI_MODEL_REWRITE: str = "gemini-3.1-flash-lite"

    # Alias de compatibilidad hacia atrás
    @property
    def GEMINI_MODEL(self) -> str:
        return self.GEMINI_MODEL_SYNTHESIS

    # Configuración de Embeddings Multilingües, Sparse y Reranker (FastEmbed en CPU)
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-m3"
    SPARSE_MODEL_NAME: str = "Qdrant/bm25"
    RERANKER_MODEL_NAME: str = "BAAI/bge-reranker-base"
    # La dimensión (1024 para bge-m3) se autodetecta dinámicamente en search_service.py

    # Rutas de almacenamiento local de usuario (No requieren permisos de Administrador)
    APP_NAME: str = "CopilotoNormativas"
    APP_AUTHOR: str = "ArquitecturaSistemas"

    # Nombre de la colección en Qdrant
    QDRANT_COLLECTION_NAME: str = "normativas_tecnicas"

    # Carpeta de vigencia que se debe filtrar obligatoriamente
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


try:
    settings = Settings()
except Exception as e:
    print(f"[ERROR DE CONFIGURACIÓN] Faltan variables en el archivo .env: {e}")
    settings = None