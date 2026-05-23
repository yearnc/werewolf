"""FastAPI application for the Werewolf web UI."""

import asyncio
import json
import sys
from pathlib import Path

# Ensure game/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "game"))
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import Config
from web.game_runner import GameRunner

app = FastAPI(title="Werewolf Web")

# Templates and static files
BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

# Global game runner (single game at a time)
runner: GameRunner | None = None


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.post("/api/start")
async def start_game(mode: str = Form(...)):
    global runner
    config = Config.load()
    errors = config.validate()
    if errors:
        return JSONResponse({"error": "; ".join(errors)}, status_code=400)

    runner = GameRunner(config)
    asyncio.create_task(runner.start_game(mode))
    return {"status": "ok"}


@app.get("/game", response_class=HTMLResponse)
async def game_page(request: Request, mode: str = "ai"):
    return templates.TemplateResponse(request, "game.html", {"mode": mode})


@app.get("/api/stream")
async def event_stream():
    """SSE endpoint — pushes game state updates to the browser."""

    async def generate():
        # Wait for runner to be available
        for _ in range(50):  # 5 second timeout
            if runner is not None and runner.awaiter is not None:
                break
            await asyncio.sleep(0.1)

        if runner is None:
            yield f"data: {json.dumps({'error': 'no game started'}, ensure_ascii=False)}\n\n"
            return

        last_generation = 0
        # On connect / reconnect, re-emit pending decision if any
        pending = runner.awaiter.get_pending_decision()
        if pending:
            yield f"data: {json.dumps(pending, ensure_ascii=False)}\n\n"

        async for state in runner.awaiter.state_queue_iter():
            # Always forward waiting states
            if state.get("waiting_for_human"):
                yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"
                last_generation = max(last_generation, state.get("generation", 0))
                continue
            # Use generation number to avoid duplicates (instead of event count)
            gen = state.get("generation", 0)
            if gen <= last_generation:
                continue
            last_generation = gen
            yield f"data: {json.dumps(state, ensure_ascii=False)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/decision")
async def submit_decision(decision_id: str = Form(...), value: str = Form("")):
    if runner is None:
        return JSONResponse({"error": "No game running"}, status_code=400)

    # Parse the value — could be int, string, or JSON
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        parsed = value

    success = runner.submit_decision(decision_id, parsed)
    return {"status": "ok" if success else "stale_decision"}
