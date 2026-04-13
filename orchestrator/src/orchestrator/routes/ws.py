from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from starlette import status
from starlette.websockets import WebSocket, WebSocketDisconnect

from orchestrator.deps import require_websocket_auth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/api/v1/sandboxes/{sandbox_id}/terminal")
async def terminal(websocket: WebSocket, sandbox_id: str) -> None:
    from orchestrator.main import app
    container = app.state.container
    if not await require_websocket_auth(websocket, container):
        return
    await websocket.accept()
    try:
        session = container.gateway.open_shell(sandbox_id)
    except Exception:  # noqa: BLE001
        logger.exception("failed to open terminal session for sandbox %s", sandbox_id)
        await websocket.close(code=1011, reason="failed to open terminal session")
        return

    stop = asyncio.Event()
    terminal_size = {"cols": 80, "rows": 24}

    def write_resize() -> None:
        session.write_channel(4, json.dumps({"Width": terminal_size["cols"], "Height": terminal_size["rows"]}))

    async def send_output() -> None:
        try:
            while not stop.is_set() and session.is_open():
                await asyncio.to_thread(session.update, 1)
                if session.peek_stdout():
                    await websocket.send_json({"type": "stdout", "data": session.read_stdout()})
                if session.peek_stderr():
                    await websocket.send_json({"type": "stderr", "data": session.read_stderr()})
                await asyncio.sleep(0.05)
            if not stop.is_set():
                logger.warning("terminal exec stream closed for sandbox %s", sandbox_id)
        except Exception:  # noqa: BLE001
            logger.exception("terminal send_output failed for sandbox %s", sandbox_id)
            raise

    async def receive_input() -> None:
        try:
            while not stop.is_set():
                try:
                    message = await websocket.receive_json()
                except WebSocketDisconnect:
                    stop.set()
                    return
                msg_type = message.get("type")
                if msg_type == "stdin":
                    session.write_stdin(message.get("data", ""))
                elif msg_type == "resize":
                    terminal_size["cols"] = message.get("cols", 80)
                    terminal_size["rows"] = message.get("rows", 24)
                    write_resize()
        except Exception:  # noqa: BLE001
            logger.exception("terminal receive_input failed for sandbox %s", sandbox_id)
            raise

    sender = asyncio.create_task(send_output())
    receiver = asyncio.create_task(receive_input())
    try:
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            with suppress(asyncio.CancelledError):
                await task
        for task in pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    finally:
        stop.set()
        session.close()


@router.websocket("/api/v1/sandboxes/{sandbox_id}/acp")
async def acp(websocket: WebSocket, sandbox_id: str) -> None:
    from orchestrator.main import app
    container = app.state.container
    if not await require_websocket_auth(websocket, container):
        return
    await websocket.accept()
    try:
        session = container.gateway.open_acp(sandbox_id)
    except Exception:  # noqa: BLE001
        logger.exception("failed to open acp session for sandbox %s", sandbox_id)
        await websocket.close(code=1011, reason="failed to open acp session")
        return

    stop = asyncio.Event()

    async def send_output() -> None:
        try:
            while not stop.is_set() and session.is_open():
                await asyncio.to_thread(session.update, 1)
                if session.peek_stdout():
                    await websocket.send_text(session.read_stdout())
                if session.peek_stderr():
                    logger.warning("acp stderr sandbox=%s: %s", sandbox_id, session.read_stderr().strip())
                await asyncio.sleep(0.05)
            if not stop.is_set():
                logger.warning("acp exec stream closed for sandbox %s", sandbox_id)
        except Exception:  # noqa: BLE001
            logger.exception("acp send_output failed for sandbox %s", sandbox_id)
            raise

    async def receive_input() -> None:
        try:
            while not stop.is_set():
                try:
                    message = await websocket.receive_text()
                except WebSocketDisconnect:
                    stop.set()
                    return
                session.write_stdin(message)
        except Exception:  # noqa: BLE001
            logger.exception("acp receive_input failed for sandbox %s", sandbox_id)
            raise

    sender = asyncio.create_task(send_output())
    receiver = asyncio.create_task(receive_input())
    try:
        done, pending = await asyncio.wait({sender, receiver}, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            with suppress(asyncio.CancelledError):
                await task
        for task in pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    finally:
        stop.set()
        session.close()
