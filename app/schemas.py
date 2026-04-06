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
    mode: str = Field(pattern="^(synth|tts)$")


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
    lyric_normalized: str | None = None
    bpm_at_start: float
    offset_ql: float
    dur_ql: float


class TempoChangeEvent(BaseModel):
    offset_ql: float
    bpm: float


class VoiceNoteEventsResponse(BaseModel):
    score_id: str
    voice: str = Field(pattern="^(soprano|contralto|tenor|baixo)$")
    bpm: float
    tempo_changes: list[TempoChangeEvent] = Field(default_factory=list)
    events: list[VoiceNoteEvent]


class PartSummary(BaseModel):
    part_index: int
    part_name: str
    midi_min: int | None = None
    midi_max: int | None = None
    midi_median: float | None = None
    has_lyrics: bool
    guessed_voice: str
    confidence: float = Field(ge=0.0, le=1.0)


class PartListResponse(BaseModel):
    score_id: str
    parts: list[PartSummary]
