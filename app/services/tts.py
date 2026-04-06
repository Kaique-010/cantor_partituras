from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI

VOICE_PROMPTS = {
    "soprano": "Cante esta linha com timbre de soprano lírico, afinação clara e fraseado coral.",
    "contralto": "Cante esta linha com timbre de contralto quente, sustentação estável e boa dicção.",
    "tenor": "Cante esta linha com timbre de tenor claro, projeção média e precisão rítmica.",
    "baixo": "Cante esta linha com timbre de baixo profundo, ataque suave e ressonância estável.",
}


def synthesize_voice(voice: str, notes_description: str, output_path: Path) -> Path:
    """
    Gera áudio da voz selecionada.

    Ajuste OPENAI_TTS_MODEL para o modelo de voz disponível na sua conta.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY não configurada")

    client = OpenAI(api_key=api_key)
    requested_model = os.environ.get("OPENAI_TTS_MODEL", "gpt-5-voice")
    voice_style = os.environ.get("OPENAI_TTS_VOICE", "ember")

    prompt = (
        f"{VOICE_PROMPTS[voice]} "
        f"Cante apenas em 'la', seguindo exatamente o BPM e a sequência em Nota/QL; 'rest' é silêncio. "
        f"Não pronuncie nomes das notas nem palavras; execute como canto sem fala. "
        f"Sequência: {notes_description}"
    )

    candidates = [
        requested_model,
        os.environ.get("OPENAI_TTS_FALLBACK_MODEL_1", "gpt-4o-mini-tts"),
        os.environ.get("OPENAI_TTS_FALLBACK_MODEL_2", "tts-1"),
        os.environ.get("OPENAI_TTS_FALLBACK_MODEL_3", "tts-1-hd"),
    ]

    seen: set[str] = set()
    models_to_try: list[str] = []
    for m in candidates:
        if m and m not in seen:
            models_to_try.append(m)
            seen.add(m)

    last_error: Exception | None = None
    for model in models_to_try:
        kwargs = {"model": model, "voice": voice_style, "input": prompt}
        try:
            try:
                with client.audio.speech.with_streaming_response.create(
                    **kwargs,
                    response_format="mp3",
                ) as response:
                    response.stream_to_file(str(output_path))
            except TypeError:
                with client.audio.speech.with_streaming_response.create(
                    **kwargs,
                ) as response:
                    response.stream_to_file(str(output_path))
            return output_path
        except Exception as e:
            last_error = e
            status = getattr(e, "status_code", None)
            if status == 404 or e.__class__.__name__ == "NotFoundError":
                continue
            raise

    raise ValueError(
        f"Modelo TTS indisponível. Tentativas: {', '.join(models_to_try)}. Erro: {last_error}"
    )

    return output_path
