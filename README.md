# say-chat

Voice chat with an LLM via tscribe + litellm.

Record your microphone, get transcribed by [tscribe](https://github.com/danielramirez/transcription-tool), send to a litellm-backed chat model, and hear the response spoken aloud through macOS `say` -- all in a continuous terminal loop with push-to-talk and multi-turn conversation history.

---

## Prerequisites

- **Python 3.10+**
- **ffmpeg** (`brew install ffmpeg`)
- **tscribe** installed globally (with remote transcription support):
  ```bash
  cd ~/repos/tscribe-transcription-tool
  uv sync
  uv tool install .
  ```
  Verify: `tscribe --help`
- **ffplay** (from ffmpeg) or **aplay** (for streaming TTS playback)

---

## Setup

```bash
cd ~/repos/say-chat
uv sync
```

Create a `.env` file in the project root (see `.env.example`):

```env
LITELLM_API_KEY=sk-...
LITELLM_BASE_URL=http://100.89.168.11:6280/v1
LITELLM_MODEL=chat
TSCRIBE_DEVICE_ID=17
TRANSCRIPTION_MODEL=Systran/faster-distil-whisper-large-v3
```

Find your microphone device ID with:

```bash
tscribe devices
```

**Note:** Transcription uses `tscribe` which now supports remote transcription via the LiteLLM API. Configure `TRANSCRIPTION_MODEL` to use the remote API, or omit it to use local Whisper.

Optional TTS settings (omit to use your system default):

```env
# SAY_VOICE=Daniel
# SAY_RATE=200
```

---

## Usage

### Basic Voice Chat (macOS say)

```bash
uv run voice-chat
# Or with a specific voice/rate:
uv run voice-chat --voice Samantha --rate 180
```

### Streaming Voice Chat (Qwen3-TTS)

```bash
uv run voice-chat-streaming
# Or with a specific TTS model:
uv run voice-chat-streaming --model custom-voice
uv run voice-chat-streaming --model voice-design
```

Requires `ffplay` (from ffmpeg) or `aplay` (from alsa-utils) for audio playback.

CLI flags:

| Flag | Default | Description |
|---|---|---|
| `--voice` | `Samantha` | TTS voice name (list: `say -v '?'`) |
| `--rate` | system default | Speech rate in words per minute |

Terminal interaction:

| Action | What to do |
|---|---|
| Start recording | Press Enter |
| Stop recording | Press Enter again |
| Quit | Type `q` and press Enter |
| Exit immediately | Press Ctrl+C |

A session looks like this:

```
say-chat v0.1.0 -- Voice chat with LLM via tscribe + litellm

Press Enter to record (or 'q' to quit)...
Recording... Press Enter to stop.
Captured 3.2s of audio.
Transcribing...
  Detected language: en (probability: 0.98)

[You] what's the capital of france?

[Assistant] The capital of France is Paris.

Press Enter to record (or 'q' to quit)...
```

---

## How It Works

**Basic voice-chat:**
```
 ┌──────────┐    ┌───────────┐    ┌──────────┐    ┌──────────┐
 │ tscribe  │───▶│ ChatClient│───▶│   say    │───▶│ Speaker  │
 │ record   │    │ (litellm) │    │ (subproc)│    │ (audio)  │
 └──────────┘    └───────────┘    └──────────┘    └──────────┘
```

**Streaming voice-chat-streaming:**
```
 ┌──────────┐    ┌───────────┐    ┌──────────────┐    ┌──────────┐
 │ tscribe  │───▶│ ChatClient│───▶│ Qwen3-TTS    │───▶│ ffplay/  │
 │ record   │    │ (litellm) │    │ Server (curl) │    │ aplay    │
 └──────────┘    └───────────┘    └──────────────┘    └──────────┘
```

1. **Record** -- wraps `tscribe record --device-id N` as a subprocess.
    Press Enter to start, Enter again to stop (sends SIGINT to tscribe).
2. **Transcribe** -- handled by tscribe (Whisper via faster-whisper).
    Output is parsed to extract raw transcript text.
3. **Chat** -- transcript + conversation history sent to the litellm
    API via direct HTTP POST. Multi-turn context is maintained.
4. **Speak** -- LLM response sent to Qwen3-TTS server with `stream: true`.
    Audio is piped directly to `ffplay` (or `aplay` as fallback) for
    real-time playback.
5. **Log** -- every exchange is appended to a timestamped file in
    `logs/`. Only the 100 most recent log files are retained.

---

## Docs

| Document | Contents |
|---|---|
| [docs/implementation-plan.md](docs/implementation-plan.md) | Full architecture, data flow, edge cases |
| [docs/usage.md](docs/usage.md) | Setup, commands, configuration reference, troubleshooting, example session |

---

## Project Structure

```
say-chat/
├── .env                  # Local config (gitignored)
├── .env.example          # Template
├── .gitignore
├── README.md
├── pyproject.toml        # uv-managed, dep: requests
├── uv.lock
├── docs/
│   ├── implementation-plan.md
│   └── usage.md
├── logs/                 # Chat logs (auto-created, last 100 kept)
└── src/
    └── say_chat/
        ├── __init__.py
        ├── cli.py        # Entry: `voice-chat`
        └── streaming_cli.py  # Entry: `voice-chat-streaming`
```

## Configuration

| Variable | Required | Default | Description |
|---|---|---|---|
| `LITELLM_API_KEY` | Yes | -- | API key for litellm |
| `LITELLM_BASE_URL` | No | `http://100.89.168.11:6280/v1` | API base URL |
| `LITELLM_MODEL` | No | `chat` | Model name |
| `TSCRIBE_DEVICE_ID` | No | `17` | Audio input device |
| `TRANSCRIPTION_MODEL` | No | -- | Remote transcription model (uses LITELLM credentials) |
| `MAX_RETRIES` | No | `3` | Max retries on rate limit (429) |
| `BACKOFF_FACTOR` | No | `1.0` | Exponential backoff factor in seconds |
| `SAY_VOICE` | No | `Samantha` | TTS voice (or set via `--voice`) |
| `SAY_RATE` | No | system default | Speech rate (or set via `--rate`) |
| `TTS_SERVER_URL` | No | `http://100.125.210.60:8001/v1/audio/speech` | Qwen3-TTS server URL |
| `TTS_MODEL` | No | `qwen3-tts-voice-clone` | TTS model name |
| `TTS_VOICE` | No | `danial` | Voice for TTS |
| `TTS_INSTRUCTIONS` | No | -- | Instructions for TTS |

Precedence (highest to lowest): CLI flags -> `.env` file -> code defaults.
