import os
import shutil
from pathlib import Path

# 1. Asegurar rutas
ROOT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT_DIR / "models_cache"
FASTEMBED_DIR = MODELS_DIR / "fastembed_cache"

MODELS_DIR.mkdir(parents=True, exist_ok=True)
FASTEMBED_DIR.mkdir(parents=True, exist_ok=True)

# 2. Desactivar flags offline para este script
for var in ["HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"]:
    os.environ.pop(var, None)

print("=== 1/3 Descargando BGE-M3 (SentenceTransformers) ===")
from sentence_transformers import SentenceTransformer
dense_path = MODELS_DIR / "bge-m3"
# Descarga y guarda el modelo completo de forma nativa
model = SentenceTransformer("BAAI/bge-m3")
model.save(str(dense_path))
print("-> BGE-M3 guardado.")

print("\n=== 2/3 Descargando BM25 (FastEmbed) ===")
from fastembed import SparseTextEmbedding
# FastEmbed descarga automáticamente el tar.gz correcto si local_files_only=False
bm25 = SparseTextEmbedding(
    model_name="Qdrant/bm25",
    cache_dir=str(FASTEMBED_DIR),
    local_files_only=False
)
# Llamada de inferencia obligatoria para que extraiga los pesos en disco
list(bm25.embed(["warmup"]))
print("-> BM25 guardado y extraído.")

print("\n=== 3/3 Descargando Reranker (FastEmbed) ===")
from fastembed.rerank.cross_encoder import TextCrossEncoder
reranker = TextCrossEncoder(
    model_name="BAAI/bge-reranker-base",
    cache_dir=str(FASTEMBED_DIR),
    local_files_only=False
)
list(reranker.rerank("query", ["doc"]))
print("-> Reranker guardado y extraído.")

print("\n===========================================")
print("¡TODOS LOS MODELOS LISTOS EN 'models_cache'!")
print("===========================================")