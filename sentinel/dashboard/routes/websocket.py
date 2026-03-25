"""WebSocket endpoint for live research cycle updates."""

from __future__ import annotations

import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

# Simple in-memory pub/sub for cycle updates
_subscribers: dict[str, list[WebSocket]] = {}


async def publish_update(cycle_id: str, event: dict) -> None:
    """Push an update to all subscribers of a cycle."""
    if cycle_id in _subscribers:
        message = json.dumps(event)
        disconnected: list[WebSocket] = []
        for ws in _subscribers[cycle_id]:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            _subscribers[cycle_id].remove(ws)


@router.websocket("/ws/research/{cycle_id}")
async def research_live(websocket: WebSocket, cycle_id: str):
    """Stream live updates for a running research cycle."""
    await websocket.accept()

    if cycle_id not in _subscribers:
        _subscribers[cycle_id] = []
    _subscribers[cycle_id].append(websocket)

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        if cycle_id in _subscribers and websocket in _subscribers[cycle_id]:
            _subscribers[cycle_id].remove(websocket)
