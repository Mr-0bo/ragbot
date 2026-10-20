# backend/llm_orchestrator.py
import re
import asyncio
import numpy as np
from typing import List, Dict, Optional, AsyncGenerator
from google import genai
from google.genai import types

from backend.config import settings
from backend.search_service import get_embedding_model

_client: Optional[genai.Client] = None

# Configuración de referencias para clasificación conversacional local
PATRON_CORTESIAS = re.compile(
    r'\b(hola|buenos\s+d[ií]as|buenas\s+(tardes|noches)|qu[eé]\s+tal|c[oó]mo\s+est[aá]s|'
    r'c[oó]mo\s+te\s+va|qu[eé]\s+hay|qu[eé]\s+onda|'
    r'muchas\s+gracias|gracias|de\s+acuerdo|ok|entendido|perfecto|excelente|vale|'
    r'por\s+tu\s+ayuda|hasta\s+luego|adi[oó]s|nos\s+vemos)\b',
    re.IGNORECASE
)

_FRASES_CONVERSACIONALES_REF = [
    "hola, ¿cómo estás?",
    "¿qué tal todo?",
    "buenos días a todos",
    "buenas tardes",
    "¿cómo te va el día de hoy?",
    "muchas gracias por tu ayuda",
    "de acuerdo, entendido, gracias",
    "hasta luego, que tengas buen día",
    "perfecto, muchas gracias"
]
_VECTORES_CONV_REF = None


def get_gemini_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings or not settings.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY no está configurada en las variables de entorno.")
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _extraer_vector_denso(texto: str) -> np.ndarray:
    """Extrae el vector denso unidimensional evitando el retorno de diccionarios en BGE-M3."""
    modelo = get_embedding_model()
    salida = modelo.encode(texto, return_dense=True, return_sparse=False)

    if isinstance(salida, dict) and "dense_vecs" in salida:
        vec = salida["dense_vecs"]
    else:
        vec = salida

    arr = np.array(vec, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr[0]
    return arr


def _get_vectores_conversacionales():
    """Cachea los vectores conversacionales normalizados en RAM."""
    global _VECTORES_CONV_REF
    if _VECTORES_CONV_REF is None:
        vectores = []
        for frase in _FRASES_CONVERSACIONALES_REF:
            vec = _extraer_vector_denso(frase)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectores.append(vec)
        _VECTORES_CONV_REF = vectores
    return _VECTORES_CONV_REF


async def clasificar_intencion_async(mensaje: str) -> str:
    """Clasifica la intención sin bloquear el Event Loop principal de FastAPI."""
    msg_limpio = mensaje.strip().lower()
    if not msg_limpio:
        return "CONVERSACIONAL"

    texto_sin_puntuacion = re.sub(r'[^\w\s]', '', msg_limpio)
    texto_sin_puntuacion = re.sub(r'h+o+l+a+', 'hola', texto_sin_puntuacion)
    texto_sin_puntuacion = re.sub(r'b+u+e+n+a+s+', 'buenas', texto_sin_puntuacion)

    residuo = PATRON_CORTESIAS.sub('', texto_sin_puntuacion).strip()
    palabras_residuo = residuo.split()

    if len(palabras_residuo) == 0:
        return "CONVERSACIONAL"

    if len(palabras_residuo) >= 4:
        return "TECNICA"

    try:
        vec_raw = await asyncio.to_thread(_extraer_vector_denso, msg_limpio)
        norm_pregunta = np.linalg.norm(vec_raw)

        if norm_pregunta > 0:
            vec_pregunta = vec_raw / norm_pregunta
            vectores_ref = _get_vectores_conversacionales()
            similitudes = [float(np.dot(vec_pregunta, v)) for v in vectores_ref]
            max_sim = max(similitudes) if similitudes else 0.0

            if max_sim >= 0.62:
                return "CONVERSACIONAL"
    except Exception as e:
        print(f"[WARN CLASIFICADOR LOCAL] Fallo al calcular similitud: {e}")

    return "TECNICA"


async def reformular_pregunta_con_historial_async(historial_mensajes: List[Dict], pregunta_actual: str) -> List[str]:
    client = get_gemini_client()

    historial_contexto = ""
    if historial_mensajes:
        ultimos_turnos = historial_mensajes[-3:]
        historial_contexto = "Historial reciente de conversación:\n" + "\n".join(
            [f"{m['rol'].upper()}: {m['contenido']}" for m in ultimos_turnos]
        ) + "\n\n"

    prompt = f"""Eres un optimizador de búsquedas vectoriales para documentación técnica y normativa.
Tu objetivo es analizar la última pregunta del usuario y convertirla en consultas directas y efectivas.

Reglas:
1. Resuelve pronombres, términos ambiguos o temas implícitos usando el historial previo.
2. Si la pregunta plantea dos o más aspectos técnicos distintos, sepárala en subconsultas independientes, una por línea.
3. Para conceptos normativos, procesos o especificaciones, genera consultas concisas basadas en palabras clave técnicas esenciales.
4. Responde ÚNICAMENTE con las consultas resultantes (una por línea), sin numeración, viñetas, guiones ni texto adicional.

{historial_contexto}Pregunta actual: {pregunta_actual}
"""

    try:
        modelo_rewrite = getattr(settings, "GEMINI_MODEL_REWRITE", "gemini-2.5-flash")
        respuesta = await client.aio.models.generate_content(
            model=modelo_rewrite,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.0)
        )
        texto_salida = respuesta.text.strip() if respuesta.text else ""
        subconsultas = [
            re.sub(r'^[0-9\.\-\*\s]+', '', linea).strip()
            for linea in texto_salida.split("\n")
            if linea.strip()
        ]
        return subconsultas if subconsultas else [pregunta_actual]
    except Exception as e:
        print(f"[WARN REFORMULACIÓN GEMINI ASYNC] Error: {e}")
        return [pregunta_actual]


async def generar_respuesta_chat_stream_async(
        system_prompt: str,
        user_prompt: str,
        historial: Optional[List[Dict]] = None
) -> AsyncGenerator[str, None]:
    """Transmite la respuesta palabra por palabra token a token desde Gemini."""
    try:
        client = get_gemini_client()
        history_contents = []

        if historial:
            for h in historial:
                rol_gemini = "user" if h["rol"] == "user" else "model"
                history_contents.append(
                    types.Content(
                        role=rol_gemini,
                        parts=[types.Part.from_text(text=h["contenido"])]
                    )
                )

        modelo_synthesis = getattr(settings, "GEMINI_MODEL_SYNTHESIS", "gemini-2.5-flash")

        chat = client.aio.chats.create(
            model=modelo_synthesis,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1
            ),
            history=history_contents
        )

        async for chunk in await chat.send_message_stream(user_prompt):
            if chunk.text:
                yield chunk.text

    except Exception as e:
        print(f"[ERROR GEMINI STREAMING] {e}")
        yield f"\n\n[Inconveniente de comunicación con el motor de IA: {e}]"


async def generar_respuesta_chat_async(system_prompt: str, user_prompt: str,
                                       historial: Optional[List[Dict]] = None) -> str:
    """Fallback síncrono completo."""
    buffer = []
    async for chunk in generar_respuesta_chat_stream_async(system_prompt, user_prompt, historial):
        buffer.append(chunk)
    return "".join(buffer)