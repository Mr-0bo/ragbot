# backend/search_service.py
import gc
import os
import sys
import threading
from typing import List, Dict, Optional, Union, Tuple
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.http import models
from FlagEmbedding import BGEM3FlagModel, FlagReranker
from backend.config import settings

DIMENSION_BGE_M3 = 1024

_lock_modelos = threading.Lock()

_qdrant_client: Optional[QdrantClient] = None
_bge_m3_model: Optional[BGEM3FlagModel] = None
_reranker_model: Optional[FlagReranker] = None


def get_embedding_model() -> BGEM3FlagModel:
    global _bge_m3_model
    with _lock_modelos:
        if _bge_m3_model is None:
            import torch

            if torch.cuda.is_available():
                dispositivo = "cuda"
            elif sys.platform == "darwin" and torch.backends.mps.is_available():
                dispositivo = "mps"
            else:
                dispositivo = "cpu"

            ruta_local = Path(settings.dense_model_path)
            modelo_origen = str(ruta_local) if (ruta_local.exists() and any(ruta_local.iterdir())) else settings.EMBEDDING_MODEL_NAME

            print(f"[INFO EMBEDDINGS] Inicializando BGE-M3 (Dense + Sparse) en: {dispositivo.upper()}", flush=True)

            _bge_m3_model = BGEM3FlagModel(
                modelo_origen,
                use_fp16=(dispositivo in ["cuda", "mps"]),
                device=dispositivo
            )
    return _bge_m3_model


def get_reranker_model() -> FlagReranker:
    global _reranker_model
    with _lock_modelos:
        if _reranker_model is None:
            import torch

            if torch.cuda.is_available():
                dispositivo = "cuda"
            else:
                dispositivo = "cpu"

            ruta_local = Path(settings.reranker_model_path)
            modelo_origen = str(ruta_local) if (ruta_local.exists() and any(ruta_local.iterdir())) else settings.RERANKER_MODEL_NAME

            print(f"[INFO RERANKER] Inicializando BGE-Reranker-v2-m3 en: {dispositivo.upper()}", flush=True)

            _reranker_model = FlagReranker(
                modelo_origen,
                use_fp16=(dispositivo == "cuda")
            )
    return _reranker_model


def get_qdrant_client() -> QdrantClient:
    global _qdrant_client
    with _lock_modelos:
        if _qdrant_client is None:
            _qdrant_client = QdrantClient(path=str(settings.qdrant_path))
            _inicializar_coleccion(_qdrant_client)
    return _qdrant_client


def _inicializar_coleccion(client: QdrantClient):
    """
    Crea o actualiza la colección para que opere obligatoriamente con almacenamiento
    en disco (on_disk=True), evitando desbordamientos de memoria RAM en local.
    """
    if not client.collection_exists(settings.QDRANT_COLLECTION_NAME):
        client.create_collection(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            vectors_config={
                "dense": models.VectorParams(
                    size=DIMENSION_BGE_M3,
                    distance=models.Distance.COSINE,
                    on_disk=True  # Vectores densos en disco
                )
            },
            sparse_vectors_config={
                "sparse": models.SparseVectorParams(
                    modifier=models.Modifier.IDF,
                    index=models.SparseIndexParams(
                        on_disk=True  # Vectores dispersos en disco
                    )
                )
            },
            hnsw_config=models.HnswConfigDiff(
                on_disk=True  # Grafo HNSW en disco
            ),
            on_disk_payload=True
        )
        print(f"[INFO QDRANT] Colección '{settings.QDRANT_COLLECTION_NAME}' creada en DISCO (Dense + Sparse).", flush=True)
    else:
        # Migración dinámica en vivo: si la colección ya existe, forzar vectores e índice a disco
        try:
            client.update_collection(
                collection_name=settings.QDRANT_COLLECTION_NAME,
                vectors_config={
                    "dense": models.VectorParamsDiff(on_disk=True)
                },
                hnsw_config=models.HnswConfigDiff(on_disk=True),
                optimizers_config=models.OptimizersConfigDiff(
                    indexing_threshold=10000,
                    memmap_threshold=10000
                )
            )
            print(f"[INFO QDRANT] Colección existente '{settings.QDRANT_COLLECTION_NAME}' optimizada a DISCO.", flush=True)
        except Exception as e:
            print(f"[WARN QDRANT] No fue necesario o falló actualizar parámetros a disco: {e}", flush=True)


def formatear_vector_disperso(diccionario_pesos: Dict[Union[str, int], float]) -> models.SparseVector:
    """Convierte el diccionario léxico de BGE-M3 {token_id: peso} al modelo SparseVector de Qdrant."""
    indices = []
    valores = []
    for token_id, peso in diccionario_pesos.items():
        indices.append(int(token_id))
        valores.append(float(peso))
    return models.SparseVector(indices=indices, values=valores)


def buscar_fragmentos(
        consultas: Union[str, List[str]],
        consulta_referencia: Optional[str] = None,
        region: str = "mexico",
        top_k: int = 6,
        recall_k: int = 15,
        max_por_doc: int = 3,
        max_por_pagina: int = 2
) -> List[Dict]:
    try:
        client = get_qdrant_client()
        modelo_embeddings = get_embedding_model()
        modelo_reranker = get_reranker_model()

        if isinstance(consultas, str):
            lista_consultas = [consultas]
        else:
            lista_consultas = consultas if consultas else [""]

        subconsultas_validas = [q.strip() for q in lista_consultas if q.strip()]
        if not subconsultas_validas:
            return []

        # Consulta que evaluará el Reranker al final (la pregunta original del usuario)
        query_para_rerank = consulta_referencia.strip() if consulta_referencia and consulta_referencia.strip() else subconsultas_validas[0]

        filtro_region = models.Filter(
            must=[
                models.FieldCondition(
                    key="region",
                    match=models.MatchValue(value=region.lower())
                )
            ]
        )

        prefetches: List[models.Prefetch] = []

        # Inferencia híbrida BGE-M3 (denso y disperso en una sola pasada)
        salida_lote = modelo_embeddings.encode(
            subconsultas_validas,
            batch_size=len(subconsultas_validas),
            return_dense=True,
            return_sparse=True
        )

        vectores_densos = salida_lote["dense_vecs"]
        vectores_dispersos = salida_lote["lexical_weights"]

        for idx in range(len(subconsultas_validas)):
            v_denso = vectores_densos[idx].tolist()
            v_disperso = formatear_vector_disperso(vectores_dispersos[idx])

            # Prefetch de canal denso (semántica)
            prefetches.append(
                models.Prefetch(
                    query=v_denso,
                    using="dense",
                    limit=recall_k,
                    filter=filtro_region
                )
            )

            # Prefetch de canal disperso (léxico exacto)
            prefetches.append(
                models.Prefetch(
                    query=v_disperso,
                    using="sparse",
                    limit=recall_k,
                    filter=filtro_region
                )
            )

        # Fusión híbrida con RRF (Reciprocal Rank Fusion) en Qdrant
        respuesta = client.query_points(
            collection_name=settings.QDRANT_COLLECTION_NAME,
            prefetch=prefetches,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=filtro_region,
            limit=settings.TOP_K_PREFETCH,
            with_payload=True
        )

        puntos_recuperados = respuesta.points or []
        if not puntos_recuperados:
            return []

        # Deduplicación y filtro por documento/página previo al reranking
        candidatos_para_rerank = []
        ids_vistos = set()

        for p in puntos_recuperados:
            if p.id in ids_vistos:
                continue

            pl = p.payload or {}
            candidatos_para_rerank.append({
                "id": p.id,
                "documento": str(pl.get("documento", "Desconocido")),
                "ruta_relativa": pl.get("ruta_relativa", ""),
                "pagina": pl.get("pagina", "N/A"),
                "contenido": pl.get("contenido", ""),
                "region": pl.get("region", region),
                "rrf_score": float(p.score)
            })
            ids_vistos.add(p.id)

        if not candidatos_para_rerank:
            return []

        # ==========================================
        # ETAPA 2: RE-RANKING CRUZADO (CROSS-ENCODER)
        # ==========================================
        pares_rerank = [[query_para_rerank, c["contenido"]] for c in candidatos_para_rerank]
        scores_rerank = modelo_reranker.compute_score(pares_rerank, normalize=True)

        if isinstance(scores_rerank, (float, int)):
            scores_rerank = [float(scores_rerank)]

        for i, score in enumerate(scores_rerank):
            candidatos_para_rerank[i]["score"] = float(score)

        # Ordenar de mayor a menor relevancia semántica cruzada
        candidatos_ordenados = sorted(candidatos_para_rerank, key=lambda x: x["score"], reverse=True)

        # Filtrar por diversidad de página y documento
        candidatos_finales = []
        conteo_doc: Dict[str, int] = {}
        conteo_pag: Dict[str, int] = {}

        for c in candidatos_ordenados:
            doc = c["documento"]
            pag = str(c["pagina"])
            clave_pag = f"{doc}_{pag}"

            if conteo_pag.get(clave_pag, 0) >= max_por_pagina:
                continue
            if conteo_doc.get(doc, 0) >= max_por_doc:
                continue

            conteo_pag[clave_pag] = conteo_pag.get(clave_pag, 0) + 1
            conteo_doc[doc] = conteo_doc.get(doc, 0) + 1

            candidatos_finales.append(c)

            if len(candidatos_finales) >= top_k:
                break

        return candidatos_finales

    except Exception as e:
        print(f"[ERROR BÚSQUEDA HÍBRIDA + RERANK] {e}", flush=True)
        return []
    finally:
        # Liberación periódica tras búsquedas intensas
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass


def eliminar_documento_por_ruta(ruta_relativa: str):
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
    if not puntos:
        return
    client = get_qdrant_client()
    client.upsert(
        collection_name=settings.QDRANT_COLLECTION_NAME,
        points=puntos
    )


def precargar_modelos_en_segundo_plano():
    try:
        print("\n[WARM-UP] Iniciando precarga silenciosa de BGE-M3 (Híbrido) y Reranker...", flush=True)
        get_embedding_model()
        get_reranker_model()
        get_qdrant_client()
        print("[WARM-UP] Modelos de búsqueda híbrida y reranking precargados exitosamente.\n", flush=True)
    except Exception as e:
        print(f"[WARM-UP WARN] Error en precarga: {e}", flush=True)