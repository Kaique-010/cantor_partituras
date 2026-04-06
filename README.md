# Music Voice Agents (Agno + GPT Voice)

Projeto base para um **novo repositório** com dois agentes principais:

1. **Agente OCR/Parser**: lê partitura (PDF, imagem ou MusicXML) e converte para um objeto estruturado.
2. **Renderizador determinístico (Synth)**: gera MIDI e renderiza áudio via SoundFont.
3. **Agente Cantor (TTS experimental)**: caminho alternativo para testes com modelos de voz da OpenAI.

## Fluxo proposto

1. Upload da partitura.
2. Normalização para MusicXML estruturado.
3. Agente de Harmonia classifica partes/vozes e progressões.
4. Separação de vozes (SATB).
5. Seleção da voz no frontend.
6. Geração de áudio determinística da voz selecionada (MIDI + SoundFont).
7. TTS opcional apenas como modo experimental.

## Stack

- **FastAPI** (API + upload)
- **Agno** (orquestração dos agentes)
- **music21** (parse e manipulação MusicXML/MIDI)
- **mido** (escrita de MIDI determinístico)
- **OpenAI API** (TTS vocal)
- Front-end simples (HTML/JS) para upload e seleção de voz

## Executar localmente

```bash
cd music_voice_agents
py -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload --port 8090
```

Acesse: `http://localhost:8090`

## Variáveis de ambiente

- `OPENAI_API_KEY` (obrigatória)
- `OPENAI_TTS_MODEL` (default: `gpt-5-voice`)
- `OPENAI_TTS_VOICE` (default: `alloy`)
- `SYNTH_SOUNDFONT_PATH` (opcional, caminho para arquivo `.sf2`)

## Endpoints principais

- `POST /api/scores/upload` → upload de partitura
- `POST /api/scores/{score_id}/analyze` → parse + separação SATB
- `GET /api/scores/{score_id}/voices` → lista vozes disponíveis
- `GET /api/scores/{score_id}/parts` → análise de partes e classificação de voz
- `GET /api/scores/{score_id}/voices/{voice}/events` → eventos com tempos por nota (bpm por nota + tempo changes)
- `POST /api/scores/{score_id}/play-synth` → gera áudio determinístico da voz selecionada
- `POST /api/scores/{score_id}/sing-tts` → gera áudio por TTS (experimental)
- `POST /api/scores/{score_id}/sing` → alias legado para `sing-tts`

## Observação

Este scaffold deixa os agentes prontos para evolução:
- adicionar OCR real para PDF/imagem (ex.: pipeline de visão),
- enriquecer o Agente de Harmonia,
- sincronizar playback com cursor da partitura no frontend.
