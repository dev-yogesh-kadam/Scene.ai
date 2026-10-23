"""A throwaway copy of the studio for the browser check (check.mjs), on port 8099, and its admin console on 8098: empty SQLite storage, the
real workflows and frontend, and a fake agent model that answers after a moment, so the live progress can be seen."""
import asyncio
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"C:\Scene\Scene.ai")
HERE = Path(tempfile.gettempdir()) / "scene-e2e"   # storage, test files and screenshots; never in the repo
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from scene import media  # noqa: E402
from scene.config import Settings  # noqa: E402
from scene.main import Doors, create_app  # noqa: E402
import uvicorn  # noqa: E402

storage = HERE / "storage"
shutil.rmtree(storage, ignore_errors=True)
(storage / "cache").mkdir(parents=True)
shutil.copy(r"C:\Scene\Data\cache\node_definitions.json", storage / "cache" / "node_definitions.json")

files = HERE / "e2e_files"
files.mkdir(parents=True, exist_ok=True)
asyncio.run(media._ffmpeg("-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=s=640x360:r=24:d=3", "-pix_fmt", "yuv420p", files / "clip.mp4"))
asyncio.run(media._ffmpeg("-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=512x512", "-frames:v", "1", files / "dog.png"))
asyncio.run(media._ffmpeg("-y", "-loglevel", "error", "-f", "lavfi", "-i", "mandelbrot=s=512x512", "-frames:v", "1", files / "cat.png"))

settings = Settings(comfy_url="http://127.0.0.1:9", ollama_url="http://127.0.0.1:9", storage_dir=str(storage), signup_credits=500,
                    first_account_local=False, workflows_dir=str(ROOT / "workflows"), frontend_dir=str(ROOT / "frontend"),
                    default_workflow="video/h3_master", backup_keep=0, port=8099, console_port=8098, hold_queue_offline=False)
app = create_app(settings)


async def fake_ask(system, message, workflow_ids, history=(), model=None):
    await asyncio.sleep(1.6)
    return {"thought": "They want a short shot of a dog. One 5 s landscape clip on the default workflow, reference mode.",
            "reply": "Here is **one shot** of the dog running across a park.\n- 5 seconds, landscape\n- low quality for a quick look",
            "steps": [{"tool": "generate", "workflow": "video/h3_master", "name": "Dog in the park",
                       "prompt": "SCENE CONTEXT: a brown dog runs across a sunny park.\nACTION: it chases a red ball.\nCAMERA: tracking shot.",
                       "duration": 5, "resolution": 480, "orientation": "landscape", "choices": [{"setting": "quality", "value": "low"}]}]}


async def fake_describe(*args, **kwargs):
    return "A test picture."

app.state.agent.ask = fake_ask


async def fake_models():
    return ["gemini/gemini-3.6-flash", "nemotron3:33b"]


async def fake_pick(wanted=None):
    return wanted or "gemini/gemini-3.6-flash"
app.state.agent.models = fake_models
app.state.agent.pick_model = fake_pick
app.state.agent.hosted = lambda: [{"id": "gemini", "name": "Gemini"}]
app.state.credits.set_llm_price("gemini/gemini-3.6-flash", 2)
app.state.agent.describe = fake_describe
listen = [socket.create_server(("127.0.0.1", port)) for port in (8099, 8098)]
uvicorn.Server(uvicorn.Config(Doors(app), log_level="warning")).run(sockets=listen)
