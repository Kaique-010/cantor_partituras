from __future__ import annotations

import logging
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.responses import Response

from app.agents.orchestrator import ScoreAgents
from app.schemas import (
    AnalyzeResponse,
    PartListResponse,
    SingRequest,
    SingResponse,
    VoiceListResponse,
    VoiceNoteEventsResponse,
    VoiceTimelineResponse,
)
from app.services.musicxml import (
    build_voice_note_events,
    build_voice_timeline,
    analyze_parts,
    export_voice_musicxml,
    build_voice_sing_script,
    infer_satb_voices,
    normalize_to_musicxml,
)
from app.services.storage import (
    parsed_musicxml_path,
    persist_upload,
    voice_audio_path,
    voice_musicxml_path,
)
from app.services.tts import synthesize_voice
from app.services.synth_renderer import render_voice_audio

router = APIRouter(prefix="/api/scores", tags=["scores"])
agents = ScoreAgents()
SCORE_DB: dict[str, dict] = {}
logger = logging.getLogger("uvicorn.error")


@router.post("/upload")
async def upload_score(file: UploadFile = File(...)) -> dict:
    content = await file.read()
    score_id, path = persist_upload(file.filename, content)
    SCORE_DB[score_id] = {
        "upload_path": str(path),
        "voices": [],
        "conversion_status": "pending",
        "conversion_error": None,
        "conversion_started_at": None,
        "conversion_finished_at": None,
    }
    return {"score_id": score_id, "upload_path": str(path)}


@router.get("/{score_id}/upload")
def get_uploaded_file(score_id: str) -> FileResponse:
    score = SCORE_DB.get(score_id)
    if not score:
        raise HTTPException(status_code=404, detail="Score não encontrado")

    path = Path(score["upload_path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo de upload não encontrado")

    suffix = path.suffix.lower()
    media_type = "application/octet-stream"
    if suffix == ".pdf":
        media_type = "application/pdf"
    elif suffix in (".png",):
        media_type = "image/png"
    elif suffix in (".jpg", ".jpeg"):
        media_type = "image/jpeg"
    elif suffix in (".webp",):
        media_type = "image/webp"
    elif suffix in (".xml", ".musicxml"):
        media_type = "application/vnd.recordare.musicxml+xml"
    elif suffix in (".mid", ".midi"):
        media_type = "audio/midi"

    return FileResponse(path, media_type=media_type, filename=path.name)


def _convert_to_musicxml_job(score_id: str) -> None:
    score = SCORE_DB.get(score_id)
    if not score:
        return

    if score.get("conversion_status") == "running":
        logger.info("OCR/normalize started score_id=%s", score_id)

    try:
        output = parsed_musicxml_path(score_id)
        normalized_path = normalize_to_musicxml(Path(score["upload_path"]), output)
        score["normalized_musicxml_path"] = str(normalized_path)
        score["conversion_status"] = "done"
        score["conversion_error"] = None
        score["conversion_finished_at"] = time.time()
        logger.info("OCR/normalize done score_id=%s", score_id)
    except Exception as e:
        score["conversion_status"] = "error"
        score["conversion_error"] = str(e)
        score["conversion_finished_at"] = time.time()
        logger.exception("OCR/normalize error score_id=%s", score_id)


def ensure_analyzed(score_id: str) -> dict:
    score = SCORE_DB.get(score_id)
    if not score:
        raise HTTPException(status_code=404, detail="Score não encontrado")

    if score.get("normalized_musicxml_path") and score.get("voices"):
        return score

    status = score.get("conversion_status") or "pending"
    if status in ("pending", "running"):
        raise HTTPException(status_code=409, detail="Conversão/OCR em andamento. Aguarde a partitura carregar.")
    if status == "error":
        raise HTTPException(status_code=400, detail=score.get("conversion_error") or "Falha ao converter partitura")

    normalized_path_str = score.get("normalized_musicxml_path")
    if normalized_path_str:
        normalized_path = Path(normalized_path_str)
        if normalized_path.is_file():
            score["voices"] = infer_satb_voices(normalized_path)
            return score

    try:
        result = agents.analyze_score(score_id=score_id, input_path=Path(score["upload_path"]))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    score["voices"] = result.voices
    score["normalized_musicxml_path"] = str(result.normalized_musicxml)
    score["parts"] = analyze_parts(Path(score["normalized_musicxml_path"]))
    return score


@router.post("/{score_id}/analyze", response_model=AnalyzeResponse)
def analyze_score(score_id: str) -> AnalyzeResponse:
    score = ensure_analyzed(score_id)
    normalized_path = Path(score["normalized_musicxml_path"])
    score["parts"] = analyze_parts(normalized_path)
    score["voices"] = sorted({p["guessed_voice"] for p in score["parts"]}) or infer_satb_voices(normalized_path)

    return AnalyzeResponse(
        score_id=score_id,
        normalized_musicxml_path=str(score["normalized_musicxml_path"]),
        voices=score["voices"],
    )


@router.get("/{score_id}/voices", response_model=VoiceListResponse)
def list_voices(score_id: str) -> VoiceListResponse:
    score = ensure_analyzed(score_id)

    voices = score.get("voices") or []
    return VoiceListResponse(score_id=score_id, voices=voices)


@router.get("/{score_id}/parts", response_model=PartListResponse)
def list_parts(score_id: str) -> PartListResponse:
    score = ensure_analyzed(score_id)
    normalized_path = Path(score["normalized_musicxml_path"])
    parts = analyze_parts(normalized_path)
    score["parts"] = parts
    return PartListResponse(score_id=score_id, parts=parts)

@router.get("/{score_id}/musicxml")
def get_musicxml(score_id: str, background_tasks: BackgroundTasks) -> Response:
    score = SCORE_DB.get(score_id)
    if not score:
        raise HTTPException(status_code=404, detail="Score não encontrado")

    normalized_path = Path(score.get("normalized_musicxml_path") or "")
    if not normalized_path.is_file():
        status = score.get("conversion_status") or "pending"
        if status in ("pending", "running"):
            if status != "running":
                score["conversion_status"] = "running"
                score["conversion_error"] = None
                score["conversion_started_at"] = time.time()
                score["conversion_finished_at"] = None
                background_tasks.add_task(_convert_to_musicxml_job, score_id)

            started_at = score.get("conversion_started_at")
            elapsed_s = None
            if isinstance(started_at, (int, float)):
                elapsed_s = int(time.time() - float(started_at))
            return JSONResponse(
                status_code=202,
                content={
                    "score_id": score_id,
                    "status": score["conversion_status"],
                    "detail": "Conversão/OCR em andamento",
                    "elapsed_s": elapsed_s,
                },
            )
        if status == "error":
            return JSONResponse(
                status_code=400,
                content={
                    "score_id": score_id,
                    "status": "error",
                    "detail": score.get("conversion_error") or "Falha ao converter partitura",
                },
            )

    return FileResponse(
        normalized_path,
        media_type="application/vnd.recordare.musicxml+xml",
        filename=f"{score_id}.musicxml",
    )


@router.get("/{score_id}/musicxml/status")
def get_musicxml_status(score_id: str) -> dict:
    score = SCORE_DB.get(score_id)
    if not score:
        raise HTTPException(status_code=404, detail="Score não encontrado")
    started_at = score.get("conversion_started_at")
    elapsed_s = None
    if isinstance(started_at, (int, float)):
        elapsed_s = int(time.time() - float(started_at))
    return {
        "score_id": score_id,
        "status": score.get("conversion_status") or "pending",
        "error": score.get("conversion_error"),
        "normalized_musicxml_path": score.get("normalized_musicxml_path"),
        "started_at": started_at,
        "finished_at": score.get("conversion_finished_at"),
        "elapsed_s": elapsed_s,
    }


@router.get("/{score_id}/voices/{voice}/musicxml")
def get_voice_musicxml(score_id: str, voice: str) -> FileResponse:
    score = ensure_analyzed(score_id)
    if voice not in (score.get("voices") or []):
        raise HTTPException(status_code=400, detail="Voz não disponível para esta partitura")

    normalized_path = Path(score["normalized_musicxml_path"])
    output = voice_musicxml_path(score_id, voice)
    if not output.exists():
        export_voice_musicxml(normalized_path, voice, output)

    return FileResponse(
        output,
        media_type="application/vnd.recordare.musicxml+xml",
        filename=f"{score_id}_{voice}.musicxml",
    )


@router.get("/{score_id}/voices/{voice}/timeline", response_model=VoiceTimelineResponse)
def get_voice_timeline(score_id: str, voice: str) -> VoiceTimelineResponse:
    score = ensure_analyzed(score_id)
    if voice not in (score.get("voices") or []):
        raise HTTPException(status_code=400, detail="Voz não disponível para esta partitura")

    normalized_path = Path(score["normalized_musicxml_path"])
    data = build_voice_timeline(normalized_path, voice)
    return VoiceTimelineResponse(score_id=score_id, voice=voice, bpm=data["bpm"], events=data["events"])


@router.get("/{score_id}/voices/{voice}/events", response_model=VoiceNoteEventsResponse)
def get_voice_events(score_id: str, voice: str) -> VoiceNoteEventsResponse:
    score = ensure_analyzed(score_id)
    if voice not in (score.get("voices") or []):
        raise HTTPException(status_code=400, detail="Voz não disponível para esta partitura")

    normalized_path = Path(score["normalized_musicxml_path"])
    data = build_voice_note_events(normalized_path, voice)
    return VoiceNoteEventsResponse(score_id=score_id, voice=voice, bpm=data["bpm"], events=data["events"])


@router.get("/{score_id}/voices/{voice}/audio")
def get_voice_audio(score_id: str, voice: str) -> FileResponse:
    score = ensure_analyzed(score_id)
    if voice not in (score.get("voices") or []):
        raise HTTPException(status_code=400, detail="Voz não disponível para esta partitura")

    output = voice_audio_path(score_id, voice)
    if not output.exists():
        raise HTTPException(status_code=404, detail="Áudio ainda não foi gerado para esta voz")

    return FileResponse(output, media_type="audio/mpeg", filename=output.name)


@router.post("/{score_id}/sing", response_model=SingResponse)
def sing_voice(score_id: str, payload: SingRequest) -> SingResponse:
    return sing_voice_tts(score_id, payload)


@router.post("/{score_id}/play-synth", response_model=SingResponse)
def play_synth(score_id: str, payload: SingRequest) -> SingResponse:
    score = ensure_analyzed(score_id)

    if payload.voice not in (score.get("voices") or []):
        raise HTTPException(status_code=400, detail="Voz não disponível para esta partitura")

    output = voice_audio_path(score_id, payload.voice)
    normalized_path = Path(score["normalized_musicxml_path"])
    try:
        render_voice_audio(normalized_path, payload.voice, output)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    audio_url = f"/api/scores/{score_id}/voices/{payload.voice}/audio"
    return SingResponse(score_id=score_id, voice=payload.voice, audio_url=audio_url, mode="synth")


@router.post("/{score_id}/sing-tts", response_model=SingResponse)
def sing_voice_tts(score_id: str, payload: SingRequest) -> SingResponse:
    score = ensure_analyzed(score_id)

    if payload.voice not in (score.get("voices") or []):
        raise HTTPException(status_code=400, detail="Voz não disponível para esta partitura")

    output = voice_audio_path(score_id, payload.voice)
    normalized_path = Path(score["normalized_musicxml_path"])
    bpm, sing_script = build_voice_sing_script(normalized_path, payload.voice)
    try:
        synthesize_voice(payload.voice, f"bpm={int(bpm)}; seq={sing_script}", output)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    audio_url = f"/api/scores/{score_id}/voices/{payload.voice}/audio"
    return SingResponse(score_id=score_id, voice=payload.voice, audio_url=audio_url, mode="tts")
