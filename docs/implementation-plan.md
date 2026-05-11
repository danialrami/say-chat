# say-chat — Voice Chat Pipeline

## Overview

say-chat is a voice chat pipeline that loops through four stages:

1. **Record** — capture microphone audio via `tscribe record`
2. **Transcribe** — speech-to-text via Whisper (handled by `tscribe`)
3. **Chat** — send transcript to a litellm OpenAI-compatible API
4. **Speak** — play the LLM response via macOS `say`

The entire pipeline runs in the terminal with push-to-talk interaction
and multi-turn conversation history.

---

## Architecture

```
                    ┌─────────────────────┐
                    │  .env               │
                    │  LITELLM_API_KEY    │
                    │  LITELLM_BASE_URL   │
                    │  LITELLM_MODEL      │
                    │  TSCRIBE_DEVICE_ID  │
                    │  SAY_VOICE          │
                    │  SAY_RATE           │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  cli.py             │
                    │  (voice-chat entry) │
                    └─────────┬───────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌──────────────────┐   ┌───────────────┐
│  tscribe      │   │  ChatClient      │   │  macOS `say`  │
│  record       │   │  (requests POST  │   │  (subprocess) │
│  (subprocess) │   │   litellm API)   │   │               │
└───────┬───────┘   └────────┬─────────┘   └───────┬───────┘
        │                    │                      │
        ▼                    ▼                      ▼
 ┌──────────────┐   ┌────────────────┐    ┌─────────────────┐
 │ sounddevice  │   │ litellm proxy  │    │ Speech Synth    │
 │ → Whisper    │   │ → LLM response │    │ → audio out     │
 └──────────────┘   └────────────────┘    └─────────────────┘
```

---

## Data Flow

```
Loop (infinite, quit with 'q'):

  1. Prompt user: "Press Enter to record (or 'q' to quit)..."
  2. User presses Enter
  3. Spawn: tscribe record --device-id N
  4. Show: "Recording... Press Enter to stop."
  5. User presses Enter
  6. Send SIGINT to tscribe subprocess
  7. tscribe stops recording, transcribes, writes to stdout
  8. Parse stdout → strip markdown wrapper → raw transcript
  9. Print "[You] {transcript}"
  10. POST transcript + conversation history to litellm /chat/completions
  11. Print "[Assistant] {response}"
  12. `say "{response}"`
  13. Append both messages to conversation history
  14. Save full exchange to log file
  15. Loop back to 1
```

---

## Components

### 1. Recorder (`tscribe` subprocess)

Wraps the globally-installed `tscribe` CLI tool.

- **Command**: `tscribe record --device-id <ID>`
- **Stop mechanism**: Send SIGINT to subprocess (simulates Ctrl+C)
- **Output parsing**: Strip markdown header (`# Transcript`, `---`, etc.)
  to extract raw user speech text
- **Error handling**: Detect no-audio or failed transcription, skip turn

### 2. ChatClient

Direct HTTP calls to the litellm OpenAI-compatible API (same endpoint
tscribe uses for `summarize`).

- **Endpoint**: `POST {base_url}/chat/completions`
- **Auth**: `Authorization: Bearer {api_key}`
- **Payload**:
  ```json
  {
    "model": "chat",
    "messages": [
      {"role": "system", "content": "..."},
      {"role": "user", "content": "..."},
      {"role": "assistant", "content": "..."}
    ],
    "temperature": 0.7,
    "max_tokens": 4096
  }
  ```
- **System prompt**: Keeps responses concise and spoken-word friendly
- **History maintenance**: Appends each user/assistant exchange, caps at
  20 turns to avoid token limits

### 3. Speaker (macOS `say`)

Simple subprocess call:

```bash
say -v <voice> -r <rate> "<text>"
```

Configurable voice and rate via `.env`.

### 4. Logger

Each chat exchange is timestamped and appended to a dated log file:

- **Directory**: `logs/`
- **Format**: `logs/YYYY-MM-DD_HH-MM-SS.log`
- **Content**:
  ```
  ── Exchange #1 ──
  [You] what's the capital of france?
  [Assistant] The capital of France is Paris.
  ── Exchange #2 ──
  [You] what's the population there?
  [Assistant] Paris has a population of about 2.1 million...
  ```
- **Retention**: Only the latest 100 log files are kept. Older logs
  are pruned on startup.

---

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `LITELLM_API_KEY` | `""` | API key for litellm endpoint |
| `LITELLM_BASE_URL` | `http://100.89.168.11:6280/v1` | litellm API base URL |
| `LITELLM_MODEL` | `chat` | Model name |
| `TSCRIBE_DEVICE_ID` | `17` | Audio input device for tscribe |
| `SAY_VOICE` | (system default) | macOS voice for TTS |
| `SAY_RATE` | `200` | Speech rate in words per minute |

Config precedence (same as tscribe): code defaults → `.env` file →
environment variables → (no CLI flags in this version).

---

## Project Structure

```
say-chat/
├── .env                  # Local config (gitignored)
├── .env.example          # Template
├── .gitignore
├── README.md
├── pyproject.toml        # uv-managed, deps: requests
├── docs/
│   └── implementation-plan.md
├── logs/                 # Chat logs (gitignored)
└── src/
    └── say_chat/
        ├── __init__.py
        └── cli.py        # Entry point: `voice-chat`
```

---

## Dependencies

Only `requests>=2.31` — audio pipeline handled entirely through the
globally-installed `tscribe` CLI (which manages `sounddevice`,
`faster-whisper`, etc.).

### System Prerequisites

- **Python 3.10+**
- **ffmpeg** (`brew install ffmpeg`)
- **tscribe** installed globally:
  ```bash
  cd ~/repos/tscribe-transcription-tool
  uv tool install .
  ```

---

## Edge Cases & Error Handling

| Scenario | Behavior |
|---|---|
| No audio captured | Print warning, skip API call, continue loop |
| litellm API down | Print error with guidance, continue loop |
| Auth failure (401) | Print "Check LITELLM_API_KEY", continue loop |
| Empty transcript (user silent) | Skip turn, prompt again |
| History too long | Trim oldest messages, keep last 20 turns |
| Ctrl+C at main loop | Clean exit with goodbye message |
| `tscribe` not found | Clear install guidance error |
| Log directory missing | Auto-create on first exchange |

---

## Terminal UX

```
$ voice-chat
say-chat v0.1.0 — Voice chat with LLM via tscribe + litellm
─────────────────────────────────────────────────────────────
Press Enter to record (or 'q' to quit)...
[Recording... Press Enter to stop.]
[You] what's the capital of france?
[Assistant] The capital of France is Paris.

Press Enter to record (or 'q' to quit)...
[Recording... Press Enter to stop.]
[You] what's the population there?
[Assistant] Paris has a population of about 2.1 million in the city,
and over 12 million in the greater metropolitan area.

Press Enter to record (or 'q' to quit)...
q
Goodbye.
```
