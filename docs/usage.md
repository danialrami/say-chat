# say-chat Usage Guide

## Quick Start

```bash
cd ~/repos/say-chat
uv sync
# Create .env (see Setup below)
uv run voice-chat
```

A single line of dashes (or the `.env` reference) shows it started correctly:
```
say-chat v0.1.0 -- Voice chat with LLM via tscribe + litellm

Press Enter to record (or 'q' to quit)...
```

---

## Setup

### 1. Install tscribe (one time)

```bash
cd ~/repos/tscribe-transcription-tool
uv tool install .
```

### 2. Configure .env

```
LITELLM_API_KEY=sk-...
LITELLM_BASE_URL=http://100.89.168.11:6280/v1
LITELLM_MODEL=chat
TSCRIBE_DEVICE_ID=17
SAY_VOICE=Samantha
SAY_RATE=200
```

- `TSCRIBE_DEVICE_ID` — find yours with `tscribe devices`
- `SAY_VOICE` and `SAY_RATE` are optional. List voices: `say -v '?'`

### 3. Verify setup

```bash
uv run voice-chat
```

If you see the banner and prompt, everything is wired correctly.

---

## Conversation Flow

```
┌──────────────────────────────────────────────┐
│  Banner + prompt shown                        │
│  "Press Enter to record (or 'q' to quit)..."  │
├──────────────────────────────────────────────┤
│  ↓ User presses Enter                         │
├──────────────────────────────────────────────┤
│  Recording starts (tscribe subprocess)        │
│  "Recording... Press Enter to stop."          │
│  tscribe progress visible on stderr           │
├──────────────────────────────────────────────┤
│  ↓ User presses Enter again                   │
├──────────────────────────────────────────────┤
│  Audio is transcribed (Whisper)               │
│  Duration + language info shown               │
├──────────────────────────────────────────────┤
│  Transcript sent to LLM                       │
│  Response printed and spoken aloud            │
├──────────────────────────────────────────────┤
│  Loop back to prompt                          │
└──────────────────────────────────────────────┘
```

### Example session

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

## Commands

| Action | What to do |
|---|---|
| Start recording | Press Enter at the prompt |
| Stop recording | Press Enter again |
| Quit | Type `q` and press Enter |
| Exit immediately | Press Ctrl+C |

### CLI flags

```bash
# Use a specific TTS voice
uv run voice-chat --voice Alex

# Set speech rate
uv run voice-chat --voice Samantha --rate 180

# List available voices
say -v '?'
```

| Flag | Default | Description |
|---|---|---|
| `--voice` | `Samantha` | macOS TTS voice name |
| `--rate` | system default | Speech rate in words per minute |

CLI flags take precedence over `.env` settings.

---

## Configuration Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `LITELLM_API_KEY` | Yes | — | litellm API key |
| `LITELLM_BASE_URL` | No | `http://100.89.168.11:6280/v1` | API base URL |
| `LITELLM_MODEL` | No | `chat` | Model name |
| `TSCRIBE_DEVICE_ID` | No | `17` | Audio input device index |
| `SAY_VOICE` | No | `Samantha` | TTS voice (set via .env or `--voice`) |
| `SAY_RATE` | No | system default | Speech rate in wpm |

Config precedence (highest to lowest): CLI flags → `.env` file →
environment variables → code defaults.

---

## Logging

Each session is saved to `logs/` with a timestamped filename:

```
logs/2026-05-11_14-30-00.log
```

Each log contains all exchanges from that session:

```
-- Exchange #1 --
[You] what's the capital of france?
[Assistant] The capital of France is Paris.

-- Exchange #2 --
[You] what's the population there?
[Assistant] About 2.1 million in the city proper.
```

Only the 100 most recent log files are kept; older files are
automatically pruned when the pipeline starts.

---

## Troubleshooting

### "tscribe not found"

```bash
cd ~/repos/tscribe-transcription-tool
uv tool install .
```

Verify: `tscribe --version`

### "LITELLM_API_KEY not set"

Create a `.env` file in the project root:

```
LITELLM_API_KEY=sk-...
```

### litellm connection errors

```
[Error] Could not connect to http://...
```

Check `LITELLM_BASE_URL` in `.env` and verify the litellm proxy is
running and reachable.

### Authentication errors

```
[Error] litellm API authentication failed.
```

Check `LITELLM_API_KEY` is correct and has not expired.

### No audio detected

If you see `(no audio detected)` after recording:
- Check `TSCRIBE_DEVICE_ID` with `tscribe devices`
- Ensure your microphone is not muted
- Speak clearly and ensure you're close enough to the mic

---

## Architecture

See [docs/implementation-plan.md](implementation-plan.md) for the
full architecture, data flow diagram, and component details.
