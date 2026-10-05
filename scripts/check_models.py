"""Check the agent's models: the local Ollama server and every hosted service that has a key.

Run it from the repo root with the project's Python:

    .venv\\Scripts\\python.exe scripts\\check_models.py        (Windows)
    .venv/bin/python scripts/check_models.py                   (macOS, Linux)

It never prints a key: only whether one is set, how long it is, and whether git could publish it.
"""

import asyncio
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")

from scene.agent import Agent, AgentError, service  # noqa: E402
from scene.config import load_settings  # noqa: E402


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


async def main():
    s = load_settings()
    services = [service(s.api_name.strip().lower().replace(" ", "-") or "api", s.api_name, s.api_url, s.api_key, s.api_models),
                service("gemini", "Gemini", s.gemini_url, s.gemini_key, s.gemini_models, only=r"^gemini-[\d.]+-(pro|flash)(-lite)?(-preview)?$")]
    keys = [x["key"] for x in services if x["key"]]

    print("Is a key anywhere git could publish it?")
    print("  config.json ignored by git :", git("check-ignore", "-q", "config.json").returncode == 0)
    print("  config.json tracked by git :", git("ls-files", "--error-unmatch", "config.json").returncode == 0)
    print("  a key in a staged file     :", any(git("grep", "--cached", "-q", "-F", k).returncode == 0 for k in keys))
    print("  a key in a past commit     :", any(git("log", "--all", "--oneline", "-S", k).stdout.strip() for k in keys))

    brain = Agent(s.ollama_url, s.agent_model, services)
    question = [{"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Reply with the JSON object {\"ok\": true}."}]

    def hide(text):
        for k in keys:
            text = text.replace(k, "<key>")
        return text

    print("\nOllama at", s.ollama_url)
    local = await brain._local_models()
    print("  not answering" if local is None else "  models: {}".format(local))

    for x in services:
        print("\n{} at {}".format(x["name"], x["url"] or "(no address)"))
        switched_off = str({"gemini": s.gemini_models}.get(x["id"], s.api_models)).strip().lower() in ("off", "none")
        print("  switched off in config.json (its models are set to \"off\")" if switched_off else
              "  key: set, {} characters".format(len(x["key"])) if x["key"] else "  key: NOT SET, so it is not offered")
        if x["id"] not in brain.services:
            continue
        names = [n for n in await brain._hosted_models() if n.startswith(x["id"] + "/")]
        print("  models offered:", [n.split("/", 1)[1] for n in names] or "none (the list could not be read)")
        for name in names[:4]:
            try:
                answer = await brain.chat(question, "json", model=name)
                print("  chat with {:30} works, answered {}".format(name.split("/", 1)[1], answer))
            except AgentError as e:
                print("  chat with {:30} FAILED: {}".format(name.split("/", 1)[1], hide(str(e))))
    print("\nDefault model:", s.agent_model or "(the first one there is)")

asyncio.run(main())
