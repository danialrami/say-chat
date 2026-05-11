import argparse
import os
import signal
import subprocess
import sys
import threading
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
        "say_voice": os.environ.get("SAY_VOICE", None),
        "say_rate": os.environ.get("SAY_RATE"),
    }


# ── Recorder (tscribe subprocess) ─────────────────────────────────────

def extract_transcript(output: str) -> str:
    """Strip markdown wrapper from tscribe record stdout."""
    lines = output.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == "---":
            return "\n".join(lines[i + 1 :]).strip()
    return output.strip()


def record_audio(device_id: int) -> str | None:
    """Record and transcribe via tscribe. Returns transcript text or None."""
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
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
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
        response.raise_for_status()

        result = response.json()
        reply = result["choices"][0]["message"]["content"].strip()
        self.messages.append({"role": "assistant", "content": reply})

        if len(self.messages) > 41:
            self.messages = [self.messages[0]] + self.messages[-40:]

        return reply


# ── Speaker ───────────────────────────────────────────────────────────

def speak(text: str, voice: str | None = None, rate: str | None = None):
    cmd = ["say"]
    if voice:
        cmd.extend(["-v", voice])
    if rate:
        cmd.extend(["-r", str(rate)])
    cmd.append(text)
    subprocess.run(cmd, check=True, stderr=subprocess.DEVNULL)


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

BANNER = "say-chat v0.1.0 -- Voice chat with LLM via tscribe + litellm"


def main():
    parser = argparse.ArgumentParser(description="Voice chat with LLM via tscribe + litellm")
    parser.add_argument("--voice", help="TTS voice for say (default: Samantha)")
    parser.add_argument("--rate", type=str, help="Speech rate in words per minute")
    args, _ = parser.parse_known_args()

    config = load_config()

    if args.voice:
        config["say_voice"] = args.voice
    if args.rate:
        config["say_rate"] = args.rate

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
    )

    print(BANNER)
    exchange_num = 0

    log_dir.mkdir(parents=True, exist_ok=True)
    prune_logs(log_dir, max_files=100)
    session_log = log_dir / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.log"

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
                speak(assistant_text, voice=config["say_voice"], rate=config["say_rate"])
            except subprocess.CalledProcessError as e:
                print(f"\n[Error] say command failed: {e}", file=sys.stderr)

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
