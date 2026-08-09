"""FastAPI app serving the target board and its websocket feed."""
from __future__ import annotations

import asyncio
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

STATIC = pathlib.Path(__file__).parent / "static"


def create_app(controller, start_input, stop_input) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        controller.attach_loop(asyncio.get_running_loop())
        start_input()
        yield
        stop_input()

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/state")
    async def state():
        return controller.snapshot()

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        q = controller.subscribe()
        try:
            await sock.send_json(controller.snapshot())
            while True:
                await sock.send_json(await q.get())
        except WebSocketDisconnect:
            pass
        finally:
            controller.unsubscribe(q)

    return app
