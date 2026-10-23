# ingestion/ingest_docs.py
import gc
import os
import re
import time
import uuid
import hashlib
from pathlib import Path
from typing import Callable, Optional, List
from qdrant_client.http import models

# Import condicional de PyTorch para vaciado de caché VRAM
try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

from backend.config import settings
from backend.database import SessionLocal, DocumentoNormativo
from ingestion.document_parser import extraer_markdown_de_pdf
from backend.search_service import (
    eliminar_documento_por_ruta,
    indexar_chunks_documento,
    get_embedding_model,
    formatear_vector_disperso
)


def liberar_memoria():
    """Fuerza la recolección de basura del sistema y vacía el búfer de VRAM en CUDA."""
    gc.collect()
    if HAS_TORCH and torch.cuda.is_available():
        torch.cuda.empty_cache()


def calcular_hash_md5(ruta_archivo: Path) -> str:
    hasher = hashlib.md5()
    with open(ruta_archivo, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def forzar_hidratacion_onedrive(ruta_pdf: Path, timeout_segundos: int = 45) -> bool:
    if os.name == "nt":
        os.system(f'attrib -U "{ruta_pdf}" >nul 2>&1')

    inicio = time.time()
    while time.time() - inicio < timeout_segundos:
        try:
            with open(ruta_pdf, "rb") as f:
                primeros_bytes = f.read(1024)
                if len(primeros_bytes) > 0 and ruta_pdf.stat().st_size > 0:
                    return True
        except (PermissionError, OSError):
            time.sleep(1)

    return False


def limpiar_texto(texto: str) -> str:
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n\s*\n+", "\n\n", texto)
    return texto.strip()


def dividir_en_chunks(
        texto: str,
        chunk_size: int = 1200,
        overlap: int = 200,
        separadores: Optional[List[str]] = None
) -> List[str]:
    if not texto or not texto.strip():
        return []

    if separadores is None:
        separadores = ["\n\n", "\n", ". ", "? ", "! ", " ", ""]

    def _split_recursivo(fragmento: str, separador_idx: int) -> List[str]:
        if len(fragmento) <= chunk_size or separador_idx >= len(separadores):
            return [fragmento.strip()] if fragmento.strip() else []

        sep = separadores[separador_idx]
        partes = fragmento.split(sep) if sep else list(fragmento)

        bloques = []
        bloque_actual = ""

        for parte in partes:
            candidato = f"{bloque_actual}{sep}{parte}" if bloque_actual else parte
            if len(candidato) <= chunk_size:
                bloque_actual = candidato
            else:
                if bloque_actual:
                    bloques.append(bloque_actual.strip())
                if len(parte) > chunk_size:
                    sub_bloques = _split_recursivo(parte, separador_idx + 1)
                    bloques.extend(sub_bloques)
                    bloque_actual = ""
                else:
                    bloque_actual = parte

        if bloque_actual:
            bloques.append(bloque_actual.strip())

        return [b for b in bloques if b]

    bloques_base = _split_recursivo(texto.strip(), 0)

    chunks_finales = []
    for i, bloque in enumerate(bloques_base):
        if i == 0 or overlap <= 0:
            chunks_finales.append(bloque)
        else:
            prev_texto = bloques_base[i - 1]
            corte_overlap = prev_texto[-overlap:]
            primer_espacio = corte_overlap.find(" ")
            if primer_espacio != -1:
                corte_overlap = corte_overlap[primer_espacio + 1:]

            chunk_combinado = f"{corte_overlap} ... {bloque}".strip()
            chunks_finales.append(chunk_combinado)

    return chunks_finales


def _es_carpeta_obsoleta(ruta_path: Path) -> bool:
    """
    Evalúa si la ruta contiene directorios de años o periodos históricos (2005-2024,
    2023-2024, 2024-2025, etc.) o palabras clave de respaldo.
    Conserva carpetas con nombres operativos y las carpetas de vigencia actual (2025-2026).
    """
    patron_rango = re.compile(r"^(\d{4})\s*[-_–]\s*(\d{4})$")

    for parte in ruta_path.parts[:-1]:
        limpio = parte.strip()

        # 1. Año simple de 4 dígitos entre 2005 y 2024
        if limpio.isdigit() and len(limpio) == 4:
            año = int(limpio)
            if 2005 <= año <= 2024:
                return True

        # 2. Rangos de años (ej. 2023-2024, 2024-2025)
        match_rango = patron_rango.match(limpio)
        if match_rango:
            año_fin = int(match_rango.group(2))
            if año_fin <= 2025:
                return True

        # 3. Marcas explícitas de archivo histórico
        limpio_upper = limpio.upper()
        if any(h in limpio_upper for h in ["HISTORICOS", "HISTÓRICOS", "OBSOLETOS"]):
            return True

    return False


def auditar_directorio(directorio_raiz: Path, region: str = "mexico") -> dict:
    db = SessionLocal()
    try:
        registros_bd = {
            doc.ruta_absoluta: doc
            for doc in db.query(DocumentoNormativo).all()
        }

        nuevos = []
        modificados = []
        sin_cambios = []
        encontrados_en_disco = set()

        for pdf in directorio_raiz.rglob("*.pdf"):
            if not pdf.is_file() or pdf.name.startswith("._") or pdf.name.startswith("~"):
                continue

            # Descartar archivos ubicados en carpetas de años obsoletos
            if _es_carpeta_obsoleta(pdf):
                continue

            ruta_abs = str(pdf.resolve())
            encontrados_en_disco.add(ruta_abs)

            if not forzar_hidratacion_onedrive(pdf):
                continue

            hash_actual = calcular_hash_md5(pdf)

            if ruta_abs not in registros_bd:
                nuevos.append((pdf, ruta_abs, hash_actual))
            elif registros_bd[ruta_abs].hash_md5 != hash_actual:
                modificados.append((pdf, ruta_abs, hash_actual))
            else:
                sin_cambios.append(ruta_abs)

        eliminados = [r for r in registros_bd.keys() if r not in encontrados_en_disco]

        return {
            "nuevos": nuevos,
            "modificados": modificados,
            "sin_cambios": sin_cambios,
            "eliminados": eliminados,
        }
    finally:
        db.close()


def procesar_e_indexar_archivo(
        ruta_pdf: Path,
        ruta_abs: str,
        hash_md5: str,
        region: str,
        embedding_model
) -> int:
    try:
        paginas = extraer_markdown_de_pdf(ruta_pdf, verbose=False)
    except Exception as e:
        print(f"[ERROR PARSER] Error general extrayendo '{ruta_pdf.name}': {e}", flush=True)
        liberar_memoria()
        return 0

    total_chunks = 0
    textos_chunk = []
    metadatos_chunk = []

    for item in paginas:
        num_pag = item["pagina"]
        texto_limpio = limpiar_texto(item["texto"])
        chunks = dividir_en_chunks(texto_limpio, chunk_size=1200, overlap=200)

        for idx, chunk in enumerate(chunks):
            if len(chunk) < 20:
                continue
            total_chunks += 1
            textos_chunk.append(chunk)
            metadatos_chunk.append({
                "pagina": num_pag,
                "sub_idx": idx,
                "texto": chunk,
            })

    if not textos_chunk:
        liberar_memoria()
        return 0

    # Limpiar vectores previos del archivo
    try:
        eliminar_documento_por_ruta(ruta_abs)
    except Exception as e:
        print(f"[WARN QDRANT] Error limpiando vectores antiguos de '{ruta_pdf.name}': {e}", flush=True)

    lote_size = 12
    puntos_qdrant = []

    for b in range(0, len(textos_chunk), lote_size):
        sub_lote = textos_chunk[b: b + lote_size]
        salida = embedding_model.encode(
            sub_lote,
            batch_size=len(sub_lote),
            max_length=512,
            return_dense=True,
            return_sparse=True
        )

        v_densos = salida["dense_vecs"]
        v_lexical = salida["lexical_weights"]

        for sub_i, meta_idx in enumerate(range(b, b + len(sub_lote))):
            meta = metadatos_chunk[meta_idx]
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{ruta_abs}_{meta['pagina']}_{meta['sub_idx']}"))

            vector_payload = {
                "dense": v_densos[sub_i].tolist(),
                "sparse": formatear_vector_disperso(v_lexical[sub_i])
            }

            puntos_qdrant.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector_payload,
                    payload={
                        "documento": ruta_pdf.name,
                        "ruta_relativa": ruta_abs,
                        "ruta_absoluta": ruta_abs,
                        "pagina": meta["pagina"],
                        "contenido": meta["texto"],
                        "region": region.lower(),
                    },
                )
            )

    try:
        indexar_chunks_documento(puntos_qdrant)
    except Exception as e:
        print(f"[ERROR QDRANT] Falló la inserción en Qdrant para '{ruta_pdf.name}': {e}", flush=True)

    del puntos_qdrant
    del textos_chunk
    del metadatos_chunk

    db = SessionLocal()
    try:
        doc = db.query(DocumentoNormativo).filter(DocumentoNormativo.ruta_absoluta == ruta_abs).first()
        stat = ruta_pdf.stat()
        if not doc:
            doc = DocumentoNormativo(
                id=str(uuid.uuid4()),
                nombre_archivo=ruta_pdf.name,
                ruta_absoluta=ruta_abs,
                ruta_relativa=ruta_abs,
                region=region.lower(),
                hash_md5=hash_md5,
                tamanio_bytes=stat.st_size,
                mtime=stat.st_mtime,
                total_paginas=len(paginas),
                total_chunks=total_chunks,
                esta_indexado=True,
            )
            db.add(doc)
        else:
            doc.hash_md5 = hash_md5
            doc.tamanio_bytes = stat.st_size
            doc.mtime = stat.st_mtime
            doc.total_paginas = len(paginas)
            doc.total_chunks = total_chunks
            doc.esta_indexado = True

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[ERROR DB] Falló al registrar metadatos de '{ruta_pdf.name}': {e}", flush=True)
    finally:
        db.close()
        liberar_memoria()

    return total_chunks


def sincronizar_directorio(
        directorio: str | Path,
        region: str = "mexico",
        callback_progreso: Optional[Callable[[int, int, str], None]] = None,
) -> dict:
    directorio_raiz = Path(directorio).expanduser().resolve()
    if not directorio_raiz.exists():
        raise FileNotFoundError(f"La ruta no existe: {directorio_raiz}")

    auditoria = auditar_directorio(directorio_raiz, region=region)
    db = SessionLocal()

    try:
        for ruta_abs in auditoria["eliminados"]:
            eliminar_documento_por_ruta(ruta_abs)
            db.query(DocumentoNormativo).filter(DocumentoNormativo.ruta_absoluta == ruta_abs).delete()
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[ERROR DB] Error al purgar documentos eliminados: {e}", flush=True)
    finally:
        db.close()

    a_procesar = auditoria["nuevos"] + auditoria["modificados"]
    total = len(a_procesar)
    modelo_embedding = get_embedding_model()

    chunks_totales = 0
    for idx, (pdf, ruta_abs, hash_md5) in enumerate(a_procesar, start=1):
        if callback_progreso:
            callback_progreso(idx, total, pdf.name)

        print(f"\n[SYNC ({idx}/{total})] Procesando: {pdf.name} ...", flush=True)
        chunks = procesar_e_indexar_archivo(pdf, ruta_abs, hash_md5, region, modelo_embedding)
        chunks_totales += chunks
        print(f"[SYNC ({idx}/{total})] Completado: {pdf.name} ({chunks} chunks)", flush=True)

    return {
        "nuevos_procesados": len(auditoria["nuevos"]),
        "modificados_procesados": len(auditoria["modificados"]),
        "eliminados": len(auditoria["eliminados"]),
        "sin_cambios": len(auditoria["sin_cambios"]),
        "chunks_generados": chunks_totales,
    }