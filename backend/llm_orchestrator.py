# backend/llm_orchestrator.py
import re
import asyncio
import numpy as np
from typing import List, Dict, Optional
from google import genai
from google.genai import types

from backend.config import settings
from backend.search_service import get_embedding_model

_client: Optional[genai.Client] = None

# Configuración de referencias para clasificación conversacional local
PATRON_CORTESIAS = re.compile(
    r'\b(hola|buenos\s+d[ií]as|buenas\s+(tardes|noches)|qu[eé]\s+tal|c[oó]mo\s+est[aá]s|'
    r'muchas\s+gracias|gracias|de\s+acuerdo|ok|entendido|perfecto|excelente|vale|'
    r'por\s+tu\s+ayuda|hasta\s+luego|adi[oó]s|nos\s+vemos)\b',
    re.IGNORECASE
)

_FRASES_CONVERSACIONALES_REF = [
    "hola, ¿cómo estás?",
    "buenos días a todos",
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


def _get_vectores_conversacionales():
    global _VECTORES_CONV_REF
    if _VECTORES_CONV_REF is None:
        modelo = get_embedding_model()
        vectores = []
        for frase in _FRASES_CONVERSACIONALES_REF:
            vec = np.array(modelo.encode(frase), dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectores.append(vec)
        _VECTORES_CONV_REF = vectores
    return _VECTORES_CONV_REF


def clasificar_intencion(mensaje: str) -> str:
    """Clasifica la intención limpiando primero letras repetidas en saludos comunes."""
    msg_limpio = mensaje.strip().lower()
    if not msg_limpio:
        return "CONVERSACIONAL"

    # 1. Limpieza de puntuación y letras estiradas (ej. holaaaaa -> hola)
    texto_sin_puntuacion = re.sub(r'[^\w\s]', '', msg_limpio)
    texto_sin_puntuacion = re.sub(r'h+o+l+a+', 'hola', texto_sin_puntuacion)
    texto_sin_puntuacion = re.sub(r'b+u+e+n+a+s+', 'buenas', texto_sin_puntuacion)

    residuo = PATRON_CORTESIAS.sub('', texto_sin_puntuacion).strip()
    palabras_residuo = residuo.split()

    if len(palabras_residuo) == 0:
        return "CONVERSACIONAL"

    if len(palabras_residuo) >= 4:
        return "TECNICA"

    # 2. Evaluación semántica
    try:
        modelo = get_embedding_model()
        vec_raw = np.array(modelo.encode(msg_limpio), dtype=np.float32)
        norm_pregunta = np.linalg.norm(vec_raw)

        if norm_pregunta > 0:
            vec_pregunta = vec_raw / norm_pregunta
            vectores_ref = _get_vectores_conversacionales()
            max_sim = max(float(np.dot(vec_pregunta, v)) for v in vectores_ref)

            if max_sim >= 0.65:
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
        modelo_rewrite = getattr(settings, "GEMINI_MODEL_REWRITE", "gemini-3.1-flash-lite")
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


async def generar_respuesta_chat_async(system_prompt: str, user_prompt: str,
                                       historial: Optional[List[Dict]] = None) -> str:
    """Implementa AsyncChat de Gemini para resolver la advertencia de Google SDK."""
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

        modelo_synthesis = getattr(settings, "GEMINI_MODEL_SYNTHESIS", "gemini-3.5-flash-lite")

        # Inicializamos la sesión de chat con el historial
        chat = client.aio.chats.create(
            model=modelo_synthesis,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.1
            ),
            history=history_contents
        )

        # Enviamos solo el prompt actual
        respuesta = await chat.send_message(user_prompt)
        return respuesta.text if respuesta.text else "No se obtuvo respuesta del modelo."
    except Exception as e:
        print(f"[ERROR GEMINI CHAT ASYNC] {e}")
        return "Hubo un inconveniente al comunicarse con el motor de IA. Inténtalo nuevamente."