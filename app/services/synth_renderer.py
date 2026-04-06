from __future__ import annotations

import shutil
import subprocess
import tempfile
import os
from pathlib import Path

from mido import Message, MetaMessage, MidiFile, MidiTrack, bpm2tempo

from app.services.musicxml import build_voice_note_events


DEFAULT_SOUND_FONT = Path("/usr/share/sounds/sf2/FluidR3_GM.sf2")


def _require_binary(name: str) -> None:
    if shutil.which(name) is None:
        raise ValueError(f"Binário obrigatório não encontrado: {name}")


def _events_to_midi(events: list[dict], bpm: float, midi_path: Path) -> Path:
    ticks_per_beat = 480
    midi = MidiFile(ticks_per_beat=ticks_per_beat)
    track = MidiTrack()
    midi.tracks.append(track)
    track.append(MetaMessage("set_tempo", tempo=bpm2tempo(bpm), time=0))

    queue: list[tuple[int, Message]] = []
    for event in events:
        start_tick = int(round(float(event["offset_ql"]) * ticks_per_beat))
        dur_tick = max(1, int(round(float(event["dur_ql"]) * ticks_per_beat)))
        for note in event["midi"]:
            queue.append((start_tick, Message("note_on", note=int(note), velocity=90, time=0)))
            queue.append((start_tick + dur_tick, Message("note_off", note=int(note), velocity=0, time=0)))

    queue.sort(key=lambda x: (x[0], 0 if x[1].type == "note_off" else 1))

    last_tick = 0
    for tick, msg in queue:
        msg.time = tick - last_tick
        track.append(msg)
        last_tick = tick

    midi.save(str(midi_path))
    return midi_path


def render_voice_audio(
    musicxml_path: Path,
    voice: str,
    output_mp3: Path,
    soundfont_path: Path | None = None,
) -> Path:
    _require_binary("fluidsynth")
    _require_binary("ffmpeg")

    sf2_env = os.environ.get("SYNTH_SOUNDFONT_PATH")
    sf2 = soundfont_path or (Path(sf2_env) if sf2_env else DEFAULT_SOUND_FONT)
    if not sf2.is_file():
        raise ValueError(
            "SoundFont não encontrado. Configure SYNTH_SOUNDFONT_PATH ou instale um .sf2 no sistema."
        )

    data = build_voice_note_events(musicxml_path, voice)
    bpm = float(data["bpm"])
    events = data["events"]

    output_mp3.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="synth_render_") as tmpdir:
        tmp = Path(tmpdir)
        midi_path = tmp / "voice.mid"
        wav_path = tmp / "voice.wav"

        _events_to_midi(events=events, bpm=bpm, midi_path=midi_path)

        subprocess.run(
            [
                "fluidsynth",
                "-ni",
                str(sf2),
                str(midi_path),
                "-F",
                str(wav_path),
                "-r",
                "44100",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(wav_path),
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "2",
                str(output_mp3),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    return output_mp3
