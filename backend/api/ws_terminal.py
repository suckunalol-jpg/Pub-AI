"""WebSocket terminal — bidirectional xterm.js <-> docker exec."""

import asyncio
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

router = APIRouter(tags=["terminal"])


@router.websocket("/api/ws/terminal/{agent_id}")
async def ws_terminal(
    websocket: WebSocket,
    agent_id: uuid.UUID,
    token: str = Query(...),
):
    # Auth: verify JWT token (inline — no dependency injection on WebSockets)
    try:
        from jose import JWTError, jwt
        from config import settings
        from api.auth import ALGORITHM
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise ValueError("Missing sub claim")
    except Exception:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    from executor.container_manager import container_manager

    # Ensure container exists
    try:
        ws_container = await container_manager.get_or_create(agent_id)
    except Exception as e:
        await websocket.send_text(f"\r\nFailed to start workspace: {e}\r\n")
        await websocket.close()
        return

    container_name = ws_container.container_name

    # Launch docker exec -i bash
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", "-i", container_name, "bash", "--login",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        await websocket.send_text("\r\ndocker not found on server\r\n")
        await websocket.close()
        return

    async def read_from_container():
        """Forward container stdout -> WebSocket."""
        try:
            while True:
                data = await proc.stdout.read(1024)
                if not data:
                    break
                await websocket.send_bytes(data)
        except Exception:
            pass

    async def write_to_container():
        """Forward WebSocket -> container stdin."""
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                data = msg.get("bytes") or (msg.get("text", "").encode("utf-8"))
                if data and proc.stdin:
                    proc.stdin.write(data)
                    await proc.stdin.drain()
        except (WebSocketDisconnect, Exception):
            pass

    reader_task = asyncio.create_task(read_from_container())
    writer_task = asyncio.create_task(write_to_container())

    try:
        await asyncio.wait(
            [reader_task, writer_task],
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        reader_task.cancel()
        writer_task.cancel()
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
