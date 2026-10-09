# scripts/descargar_modelos.py
import os
import sys
from pathlib import Path

# Limpiar bloqueos de red en el proceso
for k in ["HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"]:
    os.environ.pop(k, None)

ROOT_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = ROOT_DIR / "models_cache"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

print(f"=== INICIANDO DESCARGA EN: {MODELS_DIR} ===")

# 1. BGE-M3 (SentenceTransformers)
dense_path = MODELS_DIR / "bge-m3"
if not (dense_path / "model.safetensors").exists() and not (dense_path / "pytorch_model.bin").exists():
    print("\n[1/3] Descargando y guardando BGE-M3...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer("BAAI/bge-m3")
    model.save(str(dense_path))
    print(" -> BGE-M3 listo.")
else:
    print("\n[1/3] BGE-M3 ya existe en disco. Omitiendo.")

# 2. FastEmbed BM25 (permitiendo descarga explícitamente)
fastembed_dir = str(MODELS_DIR / "fastembed_cache")
print("\n[2/3] Descargando FastEmbed BM25...")
from fastembed import SparseTextEmbedding
bm25 = SparseTextEmbedding(
    model_name="Qdrant/bm25",
    cache_dir=fastembed_dir,
    local_files_only=False  # <-- Permite la descarga inicial
)
# Forzar la extracción
resultado_bm25 = list(bm25.embed(["test de inicialización"]))
print(f" -> BM25 descargado y probado ({len(resultado_bm25)} vector generado).")

# 3. FastEmbed Reranker
print("\n[3/3] Descargando FastEmbed Reranker (bge-reranker-base)...")
from fastembed.rerank.cross_encoder import TextCrossEncoder
reranker = TextCrossEncoder(
    model_name="BAAI/bge-reranker-base",
    cache_dir=fastembed_dir,
    local_files_only=False  # <-- Permite la descarga inicial
)
# Forzar la extracción
resultado_rerank = list(reranker.rerank("consulta", ["documento"]))
print(f" -> Reranker descargado y probado ({len(resultado_rerank)} score generado).")

print("\n" + "=" * 55)
print("¡TODOS LOS MODELOS DESCARGADOS Y OPERATIVOS EN LOCAL!")
print("=" * 55)