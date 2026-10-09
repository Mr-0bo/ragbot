# scripts/descargar_modelos.py
import sys
from pathlib import Path
from sentence_transformers import SentenceTransformer
from fastembed import SparseTextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

# Carpeta destino dentro del proyecto
ROOT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT_DIR / "models_cache"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

print(f"[1/3] Descargando y guardando BGE-M3 en {MODELS_DIR / 'bge-m3'}...")
dense_path = MODELS_DIR / "bge-m3"
dense_model = SentenceTransformer("BAAI/bge-m3")
dense_model.save(str(dense_path))

print(f"[2/3] Descargando y guardando FastEmbed BM25 en {MODELS_DIR / 'fastembed_cache'}...")
fastembed_dir = str(MODELS_DIR / "fastembed_cache")
SparseTextEmbedding(model_name="Qdrant/bm25", cache_dir=fastembed_dir)

print(f"[3/3] Descargando y guardando FastEmbed Reranker en {MODELS_DIR / 'fastembed_cache'}...")
TextCrossEncoder(model_name="BAAI/bge-reranker-base", cache_dir=fastembed_dir)

print("\n¡Descarga finalizada! Todos los modelos residen físicamente en 'models_cache/'.")