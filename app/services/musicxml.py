from __future__ import annotations

import statistics
from copy import deepcopy
from pathlib import Path

from music21 import converter, stream
from music21.tempo import MetronomeMark

from app.services.ocr import omr_to_musicxml

SATB = ["soprano", "contralto", "tenor", "baixo"]


def _guess_voice_from_median(midi_median: float | None) -> tuple[str, float]:
    if midi_median is None:
        return "tenor", 0.2
    if midi_median >= 69:
        return "soprano", 0.85
    if midi_median >= 62:
        return "contralto", 0.75
    if midi_median >= 55:
        return "tenor", 0.75
    return "baixo", 0.85


def normalize_to_musicxml(input_path: Path, output_path: Path) -> Path:
    """Converte o arquivo de entrada para MusicXML normalizado."""
    suffix = input_path.suffix.lower()
    if suffix in (".pdf", ".png", ".jpg", ".jpeg", ".webp"):
        return omr_to_musicxml(input_path, output_path)

    try:
        score = converter.parse(str(input_path))
    except Exception as e:
        raise ValueError(
            "Não foi possível ler a partitura. Envie MusicXML (.xml/.musicxml), MIDI (.mid) ou use PDF/imagem com OPENAI_API_KEY configurada para OCR/OMR."
        ) from e
    score.write("musicxml", fp=str(output_path))
    return output_path


def infer_satb_voices(musicxml_path: Path) -> list[str]:
    """Heurística inicial: tenta mapear partes para SATB; fallback em todas as vozes."""
    names = [item["guessed_voice"] for item in analyze_parts(musicxml_path)]

    unique = sorted(set(names))
    return unique or SATB.copy()


def analyze_parts(score: stream.Score | Path | str) -> list[dict]:
    parsed_score: stream.Score
    if isinstance(score, stream.Score):
        parsed_score = score
    else:
        parsed_score = converter.parse(str(score))

    parts_summary: list[dict] = []
    for idx, part in enumerate(parsed_score.parts):
        part_name = (part.partName or f"Part {idx + 1}").strip()
        part_name_low = part_name.lower()

        midis: list[int] = []
        has_lyrics = False
        for el in part.flatten().notesAndRests:
            if getattr(el, "isRest", False):
                continue
            if getattr(el, "isChord", False):
                midis.extend(int(p.midi) for p in el.pitches)
            else:
                midis.append(int(el.pitch.midi))
                if getattr(el, "lyrics", None):
                    has_lyrics = True

        midi_min = min(midis) if midis else None
        midi_max = max(midis) if midis else None
        midi_median = float(statistics.median(midis)) if midis else None
        guessed_voice, confidence = _guess_voice_from_median(midi_median)

        if "sopr" in part_name_low:
            guessed_voice, confidence = "soprano", 0.95
        elif "alto" in part_name_low or "contr" in part_name_low:
            guessed_voice, confidence = "contralto", 0.95
        elif "tenor" in part_name_low:
            guessed_voice, confidence = "tenor", 0.95
        elif "bass" in part_name_low or "baixo" in part_name_low:
            guessed_voice, confidence = "baixo", 0.95

        parts_summary.append(
            {
                "part_index": idx,
                "part_name": part_name,
                "midi_min": midi_min,
                "midi_max": midi_max,
                "midi_median": midi_median,
                "has_lyrics": has_lyrics,
                "guessed_voice": guessed_voice,
                "confidence": confidence,
            }
        )
    return parts_summary


def get_tempo_bpm(score: stream.Score) -> float:
    marks = [m for m in score.recurse() if isinstance(m, MetronomeMark)]
    for m in marks:
        if m.number:
            return float(m.number)
    return 120.0


def find_part_for_voice(score: stream.Score, voice: str) -> stream.Part:
    voice = voice.lower().strip()
    by_name: dict[str, stream.Part] = {}
    for part in score.parts:
        part_name = (part.partName or "").lower()
        if "sopr" in part_name:
            by_name["soprano"] = part
        if "alto" in part_name or "contr" in part_name:
            by_name["contralto"] = part
        if "tenor" in part_name:
            by_name["tenor"] = part
        if "bass" in part_name or "baixo" in part_name:
            by_name["baixo"] = part

    if voice in by_name:
        return by_name[voice]

    candidates: list[tuple[float, stream.Part]] = []
    for part in score.parts:
        pitches: list[int] = []
        for n in part.recurse().notes:
            try:
                pitches.append(int(n.pitch.midi))
            except Exception:
                continue
        if pitches:
            candidates.append((float(statistics.median(pitches)), part))

    if not candidates:
        return score.parts[0]

    candidates.sort(key=lambda x: x[0])
    parts_sorted = [p for _, p in candidates]

    if len(parts_sorted) == 1:
        return parts_sorted[0]

    if len(parts_sorted) == 2:
        low, high = parts_sorted[0], parts_sorted[-1]
        if voice in ("baixo", "tenor"):
            return low
        return high

    if len(parts_sorted) == 3:
        low, mid, high = parts_sorted[0], parts_sorted[1], parts_sorted[2]
        if voice == "baixo":
            return low
        if voice == "tenor":
            return mid
        return high

    mapping = {
        "baixo": parts_sorted[0],
        "tenor": parts_sorted[1],
        "contralto": parts_sorted[-2],
        "soprano": parts_sorted[-1],
    }
    return mapping.get(voice, parts_sorted[-1])


def export_voice_musicxml(musicxml_path: Path, voice: str, output_path: Path) -> Path:
    score: stream.Score = converter.parse(str(musicxml_path))
    part = find_part_for_voice(score, voice)
    voice_score = stream.Score()
    voice_score.insert(0, deepcopy(part))
    voice_score.write("musicxml", fp=str(output_path))
    return output_path


def extract_voice_notes_description(musicxml_path: Path, voice: str, max_events: int = 240) -> str:
    score: stream.Score = converter.parse(str(musicxml_path))
    part = find_part_for_voice(score, voice)
    items: list[str] = []

    for el in part.flatten().notesAndRests:
        if len(items) >= max_events:
            break
        dur = float(el.quarterLength)
        if el.isRest:
            items.append(f"pausa({dur})")
        elif el.isChord:
            chord_pitches = ".".join(p.nameWithOctave for p in el.pitches[:4])
            items.append(f"{chord_pitches}({dur})")
        else:
            items.append(f"{el.pitch.nameWithOctave}({dur})")

    return ", ".join(items)


def build_voice_timeline(musicxml_path: Path, voice: str) -> dict:
    score: stream.Score = converter.parse(str(musicxml_path))
    bpm = get_tempo_bpm(score)
    part = find_part_for_voice(score, voice)

    seconds_per_quarter = 60.0 / bpm
    offsets = sorted({float(el.offset) for el in part.flatten().notesAndRests})
    events = [{"t": round(off * seconds_per_quarter, 4), "offset_ql": off} for off in offsets]
    return {"bpm": bpm, "events": events}


def build_voice_sing_script(musicxml_path: Path, voice: str, max_events: int = 240) -> tuple[float, str]:
    score: stream.Score = converter.parse(str(musicxml_path))
    bpm = get_tempo_bpm(score)
    part = find_part_for_voice(score, voice)
    tokens: list[str] = []
    for el in part.flatten().notesAndRests:
        if len(tokens) >= max_events:
            break
        dur = float(el.quarterLength)
        if el.isRest:
            tokens.append(f"rest/{dur}")
        elif el.isChord:
            name = ".".join(p.nameWithOctave for p in el.pitches[:4])
            tokens.append(f"{name}/{dur}")
        else:
            tokens.append(f"{el.pitch.nameWithOctave}/{dur}")
    return bpm, ", ".join(tokens)


def build_voice_note_events(musicxml_path: Path, voice: str, max_events: int = 1000) -> dict:
    score: stream.Score = converter.parse(str(musicxml_path))
    bpm = get_tempo_bpm(score)
    part = find_part_for_voice(score, voice)
    seconds_per_quarter = 60.0 / bpm

    events: list[dict] = []
    for el in part.flatten().notesAndRests:
        if len(events) >= max_events:
            break
        offset_ql = float(el.offset)
        dur_ql = float(el.quarterLength)
        t = round(offset_ql * seconds_per_quarter, 4)
        duration = round(dur_ql * seconds_per_quarter, 4)

        midi: list[int] = []
        lyric: str | None = None
        if el.isRest:
            midi = []
        elif el.isChord:
            midi = [int(p.midi) for p in el.pitches]
            lyric = None
        else:
            midi = [int(el.pitch.midi)]
            if getattr(el, "lyrics", None):
                try:
                    lyric = el.lyrics[0].text
                except Exception:
                    lyric = None

        events.append(
            {
                "t": t,
                "duration": duration,
                "midi": midi,
                "lyric": lyric,
                "offset_ql": offset_ql,
                "dur_ql": dur_ql,
            }
        )

    return {"bpm": bpm, "events": events}
