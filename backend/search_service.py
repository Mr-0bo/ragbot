# backend/search_service.py
import os
import sys
import threading
from typing import List, Dict, Optional, Union
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.http import models
from fastembed import SparseTextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder
from backend.config import settings

DIMENSION_BGE_M3 = 1024

_lock_modelos = threading.Lock()

_qdrant_client: Optional[QdrantClient] = None
_embedding_model = None
_sparse_model: Optional[SparseTextEmbedding] = None
_reranker_model: Optional[TextCrossEncoder] = None


def get_embedding_model():
    """Carga BAAI/bge-m3 desde la carpeta local preempaquetada."""
    global _embedding_model
    with _lock_modelos:
        if _embedding_model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            if torch.cuda.is_available():
                dispositivo = "cuda"
            elif sys.platform == "darwin" and torch.backends.mps.is_available():
                dispositivo = "mps"
            else:
                dispositivo = "cpu"
                cpus = os.cpu_count() or 4
                torch.set_num_threads(cpus)

            # Priorizar la ruta local empaquetada
            ruta_local = Path(settings.dense_model_path)
            modelo_origen = str(ruta_local) if ruta_local.exists() else settings.EMBEDDING_MODEL_NAME

            print(f"[INFO EMBEDDINGS] Inicializando {modelo_origen} en: {dispositivo.upper()}")

            try:
                _embedding_model = SentenceTransformer(
                    modelo_origen,
                    device=dispositivo,
                    local_files_only=True
                )
            except Exception:
                _embedding_model = SentenceTransformer(
                    modelo_origen,
                    device=dispositivo,
                    local_files_only=False
                )

            _embedding_model.max_seq_length = 512

    return _embedding_model


def get_sparse_model() -> SparseTextEmbedding:
    """Carga BM25 directamente desde la ruta local para evitar llamadas a red o bugs con tar.gz."""
    global _sparse_model
    with _lock_modelos:
        if _sparse_model is None:
            cache_path = Path(settings.fastembed_cache_dir)
            directorio_bm25 = cache_path / "bm25"

            # Si la carpeta local existe, se pasa como ruta directa para omitir retrieve_model_gcs
            ruta_modelo = str(directorio_bm25) if directorio_bm25.exists() else settings.SPARSE_MODEL_NAME

            try:
                _sparse_model = SparseTextEmbedding(
                    model_name=ruta_modelo,
                    cache_dir=str(cache_path),
                    local_files_only=True
                )
            except Exception:
                _sparse_model = SparseTextEmbedding(
                    model_name=settings.SPARSE_MODEL_NAME,
                    cache_dir=str(cache_path),
                    local_files_only=False
                )
    return _sparse_model


def get_reranker_model() -> TextCrossEncoder:
    """Carga el Cross-Encoder directamente desde la ruta local para evitar llamadas a red."""
    global _reranker_model
    with _lock_modelos:
        if _reranker_model is None:
            cache_path = Path(settings.fastembed_cache_dir)
            directorio_reranker = cache_path / "bge-reranker-base"

            # Si la carpeta local existe, se pasa como ruta directa para omitir retrieve_model_gcs
            ruta_modelo = str(directorio_reranker) if directorio_reranker.exists() else settings.RERANKER_MODEL_NAME

            try:
                _reranker_model = TextCrossEncoder(
                    model_name=ruta_modelo,
                    cache_dir=str(cache_path),
                    local_files_only=True
                )
            except Exception:
                _reranker_model = TextCrossEncoder(
                    model_name=settings.RERANKER_MODEL_NAME,
                    cache_dir=str(cache_path),
                    local_files_only=False
                )
    return _reranker_model


def get_qdrant_client() -> QdrantClient:
    """Inicializa la base de datos vectorial local en la ruta de usuario segura."""
    global _qdrant_client
    with _lock_modelos:
        if _qdrant_client is None:
            _qdrant_client = QdrantClient(path=str(settings.qdrant_path))
            _inicializar_coleccion(_qdrant_client)
    return _qdrant_client


def _inicializar_coleccion(client: QdrantClient):
    """Crea la colección si no existe, usando dimensión fija sin cargar modelos en RAM."""
    if not client.collection_exists(settings.QDRANT_COLLECTION_NAME):
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            vectors_config={
                "dense": models.VectorParams(
                    size=DIMENSION_BGE_M3,
                    distance=models.Distance.COSINE
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(
                        on_disk=False,
                    )
                )
            }
        )


def buscar_fragmentos(
        consultas: Union[str, List[str]],
        consulta_referencia: Optional[str] = None,
        region: str = "mexico",
        top_k: int = 6,
        recall_k: int = 12,
        max_por_doc: int = 3,
        max_por_pagina: int = 2
) -> List[Dict]:
    """Pipeline bi-etápico de recuperación híbrida + reranking."""
    try:
        import torch

        client = get_qdrant_client()
        modelo_denso = get_embedding_model()
        modelo_disperso = get_sparse_model()

        if isinstance(consultas, str):
            lista_consultas = [consultas]
        else:
            lista_consultas = consultas if consultas else [""]

        subconsultas_validas = [q.strip() for q in lista_consultas if q.strip()]
        if not subconsultas_validas:
            return []

        query_rerank = (consulta_referencia or subconsultas_validas[0]).strip()

        print(f"\n[DEBUG SEARCH] Subconsultas recibidas ({len(subconsultas_validas)}): {subconsultas_validas}")
        print(f"[DEBUG SEARCH] Consulta de referencia para Reranker: '{query_rerank}'")

        filtro_region = models.Filter(
            must=[
                models.FieldCondition(
                    key="region",
                    match=models.MatchValue(value=region.lower())
                )
            ]
        )

        prefetches: List[models.Prefetch] = []
        with torch.inference_mode():
            for sub_query in subconsultas_validas:
                vector_denso = modelo_denso.encode(sub_query, normalize_embeddings=True).tolist()
                vector_disperso = list(modelo_disperso.embed([sub_query]))[0]

                prefetches.append(
                    models.Prefetch(
                        query=vector_denso,
                        using="dense",
                        limit=recall_k * 2,
                        filter=filtro_region
                    )
                )
                prefetches.append(
                    models.Prefetch(
                        query=models.SparseVector(
                            indices=vector_disperso.indices.tolist(),
                            values=vector_disperso.values.tolist()
                        ),
                        using="sparse",
                        limit=recall_k * 2,
                        filter=filtro_region
                    )
                )

        respuesta = client.query_points(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            prefetch=prefetches,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=filtro_region,
            limit=recall_k * 2,
            with_payload=True
        )

        puntos_fusionados = respuesta.points or []
        print(f"[DEBUG SEARCH] Candidatos unificados tras RRF (Fase 1): {len(puntos_fusionados)}")

        if not puntos_fusionados:
            return []

        candidatos_rerank = []
        conteo_doc_pre: Dict[str, int] = {}
        conteo_pag_pre: Dict[str, int] = {}
        ids_vistos = set()

        for p in puntos_fusionados:
            if p.id in ids_vistos:
                continue

            pl = p.payload or {}
            doc = str(pl.get("documento", "Desconocido"))
            pag = str(pl.get("pagina", "N/A"))
            clave_pag = f"{doc}_{pag}"

            if conteo_pag_pre.get(clave_pag, 0) >= max_por_pagina:
                continue
            if conteo_doc_pre.get(doc, 0) >= max_por_doc:
                continue

            ids_vistos.add(p.id)
            conteo_pag_pre[clave_pag] = conteo_pag_pre.get(clave_pag, 0) + 1
            conteo_doc_pre[doc] = conteo_doc_pre.get(doc, 0) + 1

            candidatos_rerank.append({
                "documento": doc,
                "ruta_relativa": pl.get("ruta_relativa", ""),
                "pagina": pl.get("pagina", "N/A"),
                "contenido": pl.get("contenido", ""),
                "region": pl.get("region", region),
                "score_rrf": float(p.score)
            })

            if len(candidatos_rerank) >= recall_k:
                break

        reranker = get_reranker_model()
        textos_candidatos = [c["contenido"] for c in candidatos_rerank]
        scores_rerank = list(reranker.rerank(query_rerank, textos_candidatos))

        for candidato, score_r in zip(candidatos_rerank, scores_rerank):
            candidato["score"] = float(score_r)

        candidatos_ordenados = sorted(candidatos_rerank, key=lambda x: x["score"], reverse=True)

        print(f"\n--- [EVALUACIÓN POST-RERANKING ({region.upper()})] ---")
        fragmentos_finales = candidatos_ordenados[:top_k]
        for f in fragmentos_finales:
            print(
                f"Doc: {f['documento']} | Pág: {f['pagina']} | Score Reranker: {f['score']:.4f} (RRF previo: {f['score_rrf']:.4f})")

        return fragmentos_finales

    except Exception as e:
        print(f"[ERROR BÚSQUEDA QDRANT + RERANKER] {e}")
        return []


def eliminar_documento_por_ruta(ruta_relativa: str):
    """Elimina todos los vectores asociados a un archivo modificado o borrado."""
    client = get_qdrant_client()
    client.delete(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="ruta_relativa",
                        match=models.MatchValue(value=ruta_relativa)
                    )
                ]
            )
        )
    )


def indexar_chunks_documento(puntos: List[models.PointStruct]):
    """Inserta o actualiza un lote de fragmentos vectorizados en Qdrant."""
    if not puntos:
        return
    client = get_qdrant_client()
    client.upsert(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        points=puntos
    )


def precargar_modelos_en_segundo_plano():
    """Ejecuta la precarga de modelos en segundo plano sin bloquear el servidor."""
    try:
        print("\n[WARM-UP] Iniciando precarga silenciosa de modelos en segundo plano...")
        get_embedding_model()
        get_sparse_model()
        get_reranker_model()
        get_qdrant_client()
        print("[WARM-UP] Modelos precargados exitosamente en memoria RAM. Listo para inferencia instantánea.\n")
    except Exception as e:
        print(f"[WARM-UP WARN] No se completó la precarga en background: {e}")