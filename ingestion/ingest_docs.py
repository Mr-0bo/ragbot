# ingestion/ingest_docs.py
import os
import re
import time
import uuid
import hashlib
from pathlib import Path
from typing import Callable, Optional, List
from qdrant_client.http import models

from backend.config import settings
from backend.database import SessionLocal, DocumentoNormativo
from ingestion.document_parser import extraer_markdown_de_pdf
from backend.search_service import (
    eliminar_documento_por_ruta,
    indexar_chunks_documento,
    get_embedding_model
)


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


def auditar_directorio(directorio_raiz: Path, region: str = "mexico") -> dict:
    db = SessionLocal()
    try:
        registros_bd = {
            doc.ruta_relativa: doc
            for doc in db.query(DocumentoNormativo).filter(DocumentoNormativo.region == region).all()
        }

        nuevos = []
        modificados = []
        sin_cambios = []
        encontrados_en_disco = set()

        for pdf in directorio_raiz.rglob("*"):
            if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
                continue
            if pdf.name.startswith("~") or pdf.name.startswith("."):
                continue

            if settings.CARPETA_VIGENCIA.lower() not in str(pdf).lower():
                continue

            ruta_rel = str(pdf.relative_to(directorio_raiz))
            encontrados_en_disco.add(ruta_rel)

            if not forzar_hidratacion_onedrive(pdf):
                continue

            hash_actual = calcular_hash_md5(pdf)

            if ruta_rel not in registros_bd:
                nuevos.append((pdf, ruta_rel, hash_actual))
            elif registros_bd[ruta_rel].hash_md5 != hash_actual:
                modificados.append((pdf, ruta_rel, hash_actual))
            else:
                sin_cambios.append(ruta_rel)

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
        ruta_rel: str,
        hash_md5: str,
        region: str,
        embedding_model
) -> int:
    paginas = extraer_markdown_de_pdf(ruta_pdf, verbose=False)
    puntos_qdrant = []
    total_chunks = 0

    textos_chunk = []
    metadatos_chunk = []

    for item in paginas:
        num_pag = item["pagina"]
        texto_limpio = limpiar_texto(item["texto"])
        chunks = dividir_en_chunks(texto_limpio, chunk_size=1200, overlap=200)

        for idx, chunk in enumerate(chunks):
            total_chunks += 1
            textos_chunk.append(chunk)
            metadatos_chunk.append({
                "pagina": num_pag,
                "sub_idx": idx,
                "texto": chunk,
            })

    if not textos_chunk:
        return 0

    lote_size = 64 # Cambiar a 16 o 32 en Mac M4

    for b in range(0, len(textos_chunk), lote_size):
        sub_lote = textos_chunk[b: b + lote_size]
        salida = embedding_model.encode(
            sub_lote,
            batch_size=lote_size,
            max_length=512,
            return_dense=True,
            return_sparse=False  # --- MODO DISPERSO COMENTADO ---
        )

        v_densos = salida["dense_vecs"]

        # --- MODO DISPERSO COMENTADO ---
        # v_lexical = salida["lexical_weights"]

        for sub_i, meta_idx in enumerate(range(b, b + len(sub_lote))):
            meta = metadatos_chunk[meta_idx]
            point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{ruta_rel}_{meta['pagina']}_{meta['sub_idx']}"))

            # --- MODO DISPERSO COMENTADO ---
            # lexical_dict = v_lexical[sub_i]
            # indices = [int(k) for k in lexical_dict.keys()]
            # values = [float(v) for v in lexical_dict.values()]
            # vector_hibrido = {
            #     "dense": v_densos[sub_i].tolist(),
            #     "sparse": models.SparseVector(indices=indices, values=values)
            # }

            vector_payload = {
                "dense": v_densos[sub_i].tolist()
            }

            puntos_qdrant.append(
                models.PointStruct(
                    id=point_id,
                    vector=vector_payload,
                    payload={
                        "documento": ruta_pdf.name,
                        "ruta_relativa": ruta_rel,
                        "pagina": meta["pagina"],
                        "contenido": meta["texto"],
                        "region": region.lower(),
                    },
                )
            )

    indexar_chunks_documento(puntos_qdrant)

    db = SessionLocal()
    try:
        doc = db.query(DocumentoNormativo).filter(DocumentoNormativo.ruta_relativa == ruta_rel).first()
        stat = ruta_pdf.stat()
        if not doc:
            doc = DocumentoNormativo(
                id=hash_md5,
                nombre_archivo=ruta_pdf.name,
                ruta_absoluta=str(ruta_pdf.resolve()),
                ruta_relativa=ruta_rel,
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
    finally:
        db.close()

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
        for ruta_rel in auditoria["eliminados"]:
            eliminar_documento_por_ruta(ruta_rel)
            db.query(DocumentoNormativo).filter(DocumentoNormativo.ruta_relativa == ruta_rel).delete()
        db.commit()
    finally:
        db.close()

    for _, ruta_rel, _ in auditoria["modificados"]:
        eliminar_documento_por_ruta(ruta_rel)

    a_procesar = auditoria["nuevos"] + auditoria["modificados"]
    total = len(a_procesar)

    modelo_embedding = get_embedding_model()

    chunks_totales = 0
    for idx, (pdf, ruta_rel, hash_md5) in enumerate(a_procesar, start=1):
        if callback_progreso:
            callback_progreso(idx, total, pdf.name)

        chunks = procesar_e_indexar_archivo(pdf, ruta_rel, hash_md5, region, modelo_embedding)
        chunks_totales += chunks

    return {
        "nuevos_procesados": len(auditoria["nuevos"]),
        "modificados_procesados": len(auditoria["modificados"]),
        "eliminados": len(auditoria["eliminados"]),
        "sin_cambios": len(auditoria["sin_cambios"]),
        "chunks_generados": chunks_totales,
    }


if __name__ == "__main__":
    carpeta_prueba = Path("./data")
    if carpeta_prueba.exists():
        res = sincronizar_directorio(carpeta_prueba, region="mexico")
        print(f"Resultado de sincronización: {res}")