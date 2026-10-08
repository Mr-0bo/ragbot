# ingestion/document_parser.py
from io import BytesIO
import os
from pathlib import Path
from typing import List, Dict, Union
import fitz  # PyMuPDF

# Instancia lazy de PaddleOCR para no consumir memoria al arrancar la app
_ocr_engine = None


def _get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from paddleocr import PaddleOCR
            _ocr_engine = PaddleOCR(use_angle_cls=True, lang="es")
        except Exception as e:
            print(f"[WARN] No se pudo inicializar PaddleOCR: {e}")
            _ocr_engine = False
    return _ocr_engine


def _extraer_tablas_pagina(page) -> str:
    """Extrae tablas de la página usando la detección de tablas nativa de PyMuPDF."""
    markdown_tablas = []
    try:
        tabs = page.find_tables()
        for tab in tabs:
            df = tab.extract()
            if not df or len(df) < 2:
                continue

            headers = [str(c or "").strip().replace("\n", " ") for c in df[0]]
            filas = []
            for row in df[1:]:
                fila_limpia = [str(c or "").strip().replace("\n", " ") for c in row]
                filas.append(f"| {' | '.join(fila_limpia)} |")

            separador = f"| {' | '.join(['---'] * len(headers))} |"
            tabla_md = f"| {' | '.join(headers)} |\n{separador}\n" + "\n".join(filas)
            markdown_tablas.append(tabla_md)
    except Exception:
        pass

    return "\n\n".join(markdown_tablas)


def _ejecutar_ocr_pagina(page) -> str:
    """Renderiza la página a imagen a 150 DPI y ejecuta PaddleOCR optimizado en memoria."""
    ocr = _get_ocr_engine()
    if not ocr:
        return ""

    try:
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        resultado = ocr.ocr(img_bytes, cls=True)

        del pix, img_bytes

        lineas_texto = []
        if resultado and resultado[0]:
            for linea in resultado[0]:
                lineas_texto.append(linea[1][0])

        return "\n".join(lineas_texto)
    except Exception as e:
        print(f"  [ERROR OCR] Falló OCR en pág. {page.number + 1}: {e}")
        return ""


def extraer_markdown_de_pdf(ruta_pdf: Union[str, Path]) -> List[Dict]:
    """
    Extrae el contenido de un PDF página por página en formato estructurado Markdown.
    Prioriza PyMuPDF nativo y reserva PaddleOCR estrictamente para páginas escaneadas reales.
    """
    ruta = Path(ruta_pdf)
    if not ruta.exists():
        raise FileNotFoundError(f"El archivo {ruta} no existe.")

    documento_paginas = []

    with fitz.open(ruta) as doc:
        for idx_pagina, page in enumerate(doc):
            numero_pagina = idx_pagina + 1

            # 1. Extracción de texto vectorial nativo y detección de tablas
            texto_nativo = page.get_text("text").strip()
            tablas_md = _extraer_tablas_pagina(page)

            contenido_pagina = []
            metodo = "nativo"

            # 2. Si la página tiene texto vectorial o tablas detectadas, no toca OCR
            if len(texto_nativo) >= 10 or tablas_md:
                if tablas_md:
                    contenido_pagina.append(tablas_md)
                if texto_nativo:
                    contenido_pagina.append(texto_nativo)
            else:
                # 3. Solo evaluar OCR si no hay texto y existen imágenes incrustadas
                if page.get_images():
                    texto_ocr = _ejecutar_ocr_pagina(page)
                    if texto_ocr:
                        metodo = "ocr"
                        contenido_pagina.append(texto_ocr)
                    elif texto_nativo:
                        contenido_pagina.append(texto_nativo)
                elif texto_nativo:
                    contenido_pagina.append(texto_nativo)

            texto_final = "\n\n".join(contenido_pagina).strip()

            if texto_final:
                documento_paginas.append({
                    "pagina": numero_pagina,
                    "texto": texto_final,
                    "metodo": metodo,
                })

    return documento_paginas