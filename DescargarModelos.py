# preparar_offline.py
from pathlib import Path
from sentence_transformers import SentenceTransformer
from fastembed import SparseTextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models_cache"
FASTEMBED_DIR = MODELS_DIR / "fastembed_cache"

print("[1/3] Descargando BGE-M3...")
m_dense = SentenceTransformer("BAAI/bge-m3")
m_dense.save(str(MODELS_DIR / "bge-m3"))
print("✓ BGE-M3 guardado.")

print("[2/3] Descargando BM25...")
# local_files_only=False para que lo baje de internet
m_bm25 = SparseTextEmbedding(model_name="Qdrant/bm25", cache_dir=str(FASTEMBED_DIR), local_files_only=False)
list(m_bm25.embed(["inicializar"]))
print("✓ BM25 guardado y verificado.")

print("[3/3] Descargando Reranker...")
m_rerank = TextCrossEncoder(model_name="BAAI/bge-reranker-base", cache_dir=str(FASTEMBED_DIR), local_files_only=False)
list(m_rerank.rerank("prueba", ["documento"]))
print("✓ Reranker guardado y verificado.")

print("\n¡Todo descargado con éxito en models_cache!")