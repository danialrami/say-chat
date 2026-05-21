import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import requests


# ── Config ────────────────────────────────────────────────────────────

def load_config() -> dict:
    env_path = Path.cwd() / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

    return {
        "api_key": os.environ.get("LITELLM_API_KEY", ""),
        "base_url": os.environ.get(
            "LITELLM_BASE_URL", "http://100.89.168.11:6280/v1"
        ).rstrip("/"),
        "model": os.environ.get("LITELLM_MODEL", "chat"),
        "device_id": int(os.environ.get("TSCRIBE_DEVICE_ID", "17")),
        "tts_server_url": os.environ.get(
            "TTS_SERVER_URL", "http://100.125.210.60:8001/v1/audio/speech"
        ),
        "tts_model": os.environ.get("TTS_MODEL", "qwen3-tts-voice-clone"),
        "tts_voice": os.environ.get("TTS_VOICE", "danial"),
        "tts_instructions": os.environ.get("TTS_INSTRUCTIONS", ""),
        "max_retries": int(os.environ.get("MAX_RETRIES", "3")),
        "backoff_factor": float(os.environ.get("BACKOFF_FACTOR", "1.0")),
    }


def get_model_config(model_name: str) -> dict:
    if model_name == "custom-voice":
        return {
            "model_name": "qwen3-tts-custom-voice",
            "voice": "Ryan",
            "instructions": "Speak cheerfully",
        }
    elif model_name == "voice-design":
        return {
            "model_name": "qwen3-tts-voice-design",
            "voice": "A warm, friendly male voice with a British accent",
            "instructions": "",
        }
    elif model_name == "voice-clone":
        return {
            "model_name": "qwen3-tts-voice-clone",
            "voice": "danial",
            "instructions": "",
        }
    else:
        raise ValueError(f"Unknown model: {model_name}")


# ── Recorder (tscribe subprocess) ─────────────────────────────────────

def extract_transcript(output: str) -> str:
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "---":
            return "\n".join(lines[i + 1 :]).strip()
    return output.strip()


def record_audio(device_id: int) -> str | None:
    cmd = ["tscribe", "record", "--device-id", str(device_id)]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    def stream_stderr():
        for line in iter(process.stderr.readline, ""):
            sys.stderr.write(line)
            sys.stderr.flush()

    stderr_thread = threading.Thread(target=stream_stderr, daemon=True)
    stderr_thread.start()

    print("Recording... Press Enter to stop.", file=sys.stderr, flush=True)

    try:
        input()
    except EOFError:
        pass

    process.send_signal(signal.SIGINT)
    stdout, _ = process.communicate()

    text = extract_transcript(stdout)
    if not text:
        print("\n  (no audio detected)", file=sys.stderr)
        return None
    return text


# ── ChatClient ────────────────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful voice assistant. Keep your responses concise and "
    "conversational — aim for 1-3 sentences when possible, since your "
    "answers will be spoken aloud. Be natural and friendly."
)


class ChatClient:
    def __init__(self, base_url: str, api_key: str, model: str, max_retries: int = 3, backoff_factor: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.messages = [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
        ]

    def chat(self, user_text: str) -> str:
        self.messages.append({"role": "user", "content": user_text})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": self.messages,
            "temperature": 0.7,
            "max_tokens": 4096,
        }

        for attempt in range(self.max_retries + 1):
            try:
                response = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=180,
                )

                if response.status_code == 401:
                    raise RuntimeError(
                        "liteLLM authentication failed. Check LITELLM_API_KEY."
                    )
                if response.status_code == 404:
                    raise RuntimeError(
                        f"liteLLM model '{self.model}' not found. Check LITELLM_MODEL."
                    )
                if response.status_code == 429:
                    if attempt < self.max_retries:
                        wait_time = min(self.backoff_factor * (2 ** attempt), 30)
                        print(f"\n[Rate limited] Retrying in {wait_time:.0f}s... ({attempt + 1}/{self.max_retries})", file=sys.stderr, flush=True)
                        time.sleep(wait_time)
                        continue
                    else:
                        raise RuntimeError(
                            f"Rate limit exceeded. Max retries ({self.max_retries}) reached."
                        )

                response.raise_for_status()

                result = response.json()
                reply = result["choices"][0]["message"]["content"].strip()
                self.messages.append({"role": "assistant", "content": reply})

                if len(self.messages) > 41:
                    self.messages = [self.messages[0]] + self.messages[-40:]

                return reply

            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries and isinstance(e, requests.exceptions.Timeout):
                    wait_time = min(self.backoff_factor * (2 ** attempt), 30)
                    print(f"\n[Timeout] Retrying in {wait_time:.0f}s... ({attempt + 1}/{self.max_retries})", file=sys.stderr, flush=True)
                    time.sleep(wait_time)
                    continue
                raise

        raise RuntimeError("Max retries exceeded")


# ── Streaming TTS Speaker ─────────────────────────────────────────────

def speak_streaming(
    text: str,
    server_url: str,
    model_name: str,
    voice: str,
    instructions: str,
    response_format: str = "wav",
):
    payload = {
        "model": model_name,
        "input": text,
        "voice": voice,
        "response_format": response_format,
        "stream": True,
    }
    if instructions:
        payload["instructions"] = instructions

    payload_json = json.dumps(payload)

    curl_cmd = [
        "curl", "-s", "-N", "-X", "POST", server_url,
        "-H", "Content-Type: application/json",
        "-d", payload_json,
    ]

    if response_format == "wav":
        if _find_ffplay():
            print("--- Playing WAV via ffplay ---", file=sys.stderr)
            curl_process = subprocess.Popen(curl_cmd, stdout=subprocess.PIPE)
            ffplay_cmd = ["ffplay", "-nodisp", "-autoexit", "-"]
            ffplay_process = subprocess.Popen(ffplay_cmd, stdin=curl_process.stdout)
            curl_process.stdout.close()
            ffplay_process.wait()
            curl_process.wait()
        elif _find_aplay():
            print("ffplay not found, falling back to PCM via aplay...", file=sys.stderr)
            pcm_payload = payload.copy()
            pcm_payload["response_format"] = "pcm"
            pcm_json = json.dumps(pcm_payload)
            curl_cmd[-1] = pcm_json
            curl_process = subprocess.Popen(curl_cmd, stdout=subprocess.PIPE)
            aplay_cmd = ["aplay", "-f", "S16_LE", "-r", "24000", "-c", "1"]
            aplay_process = subprocess.Popen(aplay_cmd, stdin=curl_process.stdout)
            curl_process.stdout.close()
            aplay_process.wait()
            curl_process.wait()
        else:
            print(
                "No audio player found. Install ffplay (ffmpeg) or aplay (alsa-utils).",
                file=sys.stderr,
            )
            return
    elif response_format == "pcm":
        if _find_aplay():
            print("--- Playing PCM via aplay ---", file=sys.stderr)
            curl_process = subprocess.Popen(curl_cmd, stdout=subprocess.PIPE)
            aplay_cmd = ["aplay", "-f", "S16_LE", "-r", "24000", "-c", "1"]
            aplay_process = subprocess.Popen(aplay_cmd, stdin=curl_process.stdout)
            curl_process.stdout.close()
            aplay_process.wait()
            curl_process.wait()
        else:
            print("aplay not found. Install alsa-utils.", file=sys.stderr)
            return


def _find_ffplay() -> bool:
    try:
        subprocess.run(["ffplay", "-version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _find_aplay() -> bool:
    try:
        subprocess.run(["aplay", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


# ── Logger ────────────────────────────────────────────────────────────

def prune_logs(log_dir: Path, max_files: int = 100):
    if not log_dir.exists():
        return
    files = sorted(log_dir.iterdir(), key=lambda p: p.stat().st_mtime)
    while len(files) >= max_files:
        files.pop(0).unlink()


def log_exchange(log_path: Path, exchange_num: int, user_text: str, assistant_text: str):
    with open(log_path, "a") as f:
        f.write(f"-- Exchange #{exchange_num} --\n")
        f.write(f"[You] {user_text}\n")
        f.write(f"[Assistant] {assistant_text}\n\n")


# ── Main Loop ─────────────────────────────────────────────────────────

BANNER = "say-chat-streaming v0.1.0 -- Voice chat with LLM via tscribe + litellm + Qwen3-TTS"


def main():
    parser = argparse.ArgumentParser(
        description="Voice chat with LLM via tscribe + litellm + Qwen3-TTS streaming"
    )
    parser.add_argument(
        "--model",
        choices=["custom-voice", "voice-design", "voice-clone"],
        default="voice-clone",
        help="TTS model to use (default: voice-clone)",
    )
    args, _ = parser.parse_known_args()

    config = load_config()

    model_config = get_model_config(args.model)
    tts_model_name = model_config["model_name"]
    tts_voice = model_config["voice"]
    tts_instructions = model_config["instructions"]

    if config["tts_voice"] != "danial":
        tts_voice = config["tts_voice"]
    if config["tts_instructions"]:
        tts_instructions = config["tts_instructions"]

    log_dir = Path.cwd() / "logs"

    if not _find_tscribe():
        print(
            "Error: tscribe not found. Install with:\n"
            "  cd ~/repos/tscribe-transcription-tool && uv tool install .",
            file=sys.stderr,
        )
        sys.exit(1)

    if not config["api_key"]:
        print(
            "Error: LITELLM_API_KEY not set.\n"
            "Create a .env file (see .env.example).",
            file=sys.stderr,
        )
        sys.exit(1)

    chat = ChatClient(
        base_url=config["base_url"],
        api_key=config["api_key"],
        model=config["model"],
        max_retries=config["max_retries"],
        backoff_factor=config["backoff_factor"],
    )

    print(BANNER)
    print(f"TTS Model: {args.model} ({tts_model_name})")
    print(f"TTS Voice: {tts_voice}")
    print(f"TTS Server: {config['tts_server_url']}")
    exchange_num = 0

    log_dir.mkdir(parents=True, exist_ok=True)
    prune_logs(log_dir, max_files=100)
    session_log = log_dir / f"{datetime.now():%Y-%m-%d_%H-%M-%S}_streaming.log"

    try:
        while True:
            print()
            try:
                action = input("Press Enter to record (or 'q' to quit)... ")
            except EOFError:
                break
            if action.strip().lower() in ("q", "quit", "exit"):
                break
            print()

            exchange_num += 1

            user_text = record_audio(config["device_id"])
            if user_text is None:
                exchange_num -= 1
                continue

            print(f"\n[You] {user_text}", flush=True)

            try:
                assistant_text = chat.chat(user_text)
            except requests.exceptions.ConnectionError:
                print(
                    f"\n[Error] Could not connect to {config['base_url']}",
                    file=sys.stderr,
                )
                print("Check LITELLM_BASE_URL.", file=sys.stderr)
                continue
            except RuntimeError as e:
                print(f"\n[Error] {e}", file=sys.stderr)
                continue
            except requests.exceptions.Timeout:
                print("\n[Error] Request timed out.", file=sys.stderr)
                continue

            print(f"\n[Assistant] {assistant_text}", flush=True)

            try:
                speak_streaming(
                    assistant_text,
                    server_url=config["tts_server_url"],
                    model_name=tts_model_name,
                    voice=tts_voice,
                    instructions=tts_instructions,
                )
            except subprocess.CalledProcessError as e:
                print(f"\n[Error] TTS streaming failed: {e}", file=sys.stderr)
            except Exception as e:
                print(f"\n[Error] TTS error: {e}", file=sys.stderr)

            log_exchange(session_log, exchange_num, user_text, assistant_text)

    except KeyboardInterrupt:
        print("\nGoodbye.")
        return

    print("Goodbye.")


def _find_tscribe() -> bool:
    try:
        subprocess.run(["tscribe", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


if __name__ == "__main__":
    main()
