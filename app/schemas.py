from pydantic import BaseModel, Field


class AnalyzeResponse(BaseModel):
    score_id: str
    normalized_musicxml_path: str
    voices: list[str]


class VoiceListResponse(BaseModel):
    score_id: str
    voices: list[str]


class SingRequest(BaseModel):
    voice: str = Field(pattern="^(soprano|contralto|tenor|baixo)$")


class SingResponse(BaseModel):
    score_id: str
    voice: str
    audio_url: str


class VoiceTimelineEvent(BaseModel):
    t: float
    offset_ql: float


class VoiceTimelineResponse(BaseModel):
    score_id: str
    voice: str = Field(pattern="^(soprano|contralto|tenor|baixo)$")
    bpm: float
    events: list[VoiceTimelineEvent]


class VoiceNoteEvent(BaseModel):
    t: float
    duration: float
    midi: list[int]
    lyric: str | None = None
    offset_ql: float
    dur_ql: float


class VoiceNoteEventsResponse(BaseModel):
    score_id: str
    voice: str = Field(pattern="^(soprano|contralto|tenor|baixo)$")
    bpm: float
    events: list[VoiceNoteEvent]
