# FIX: architecture_review.md — "Backend Service Layer"
# Extracted machine-related orchestration logic from main.py routes.
# These functions handle: DB operation + WebSocket notification + Redis publish.

import json
from typing import Any, Dict, List, Optional

import database as db


async def lock_machine_by_code(
    client_id: str,
    code: str,
    ttl_minutes: int,
    connected_machines: dict,
    pending_http_commands: Dict[str, List[Dict[str, Any]]],
    redis_client,
    redis_channel: str,
):
    """Lock a machine by display code. Returns the result dict from DB or raises."""
    res = await db.lock_by_code(client_id, code, ttl_minutes)
    if res is None:
        return {"error": "lock_failed"}
    if res.get("error"):
        return res

    # Notify device to lock
    machine_id = res.get("machine_id")
    payload = {"type": "lock", "expires_at": res.get("expires_at")}
    try:
        if machine_id:
            pending_http_commands.setdefault(machine_id, []).append(payload)
        ws = connected_machines.get(machine_id)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception as e:
                print("Failed to send WS lock:", e)
        if redis_client and machine_id:
            try:
                await redis_client.publish(
                    redis_channel,
                    json.dumps({"machine_id": machine_id, "payload": payload}),
                )
            except Exception as e:
                print("Failed to publish lock to redis:", e)
    except Exception:
        pass

    return res


async def unlock_machine(
    machine_id: str,
    client_id: str,
    connected_machines: dict,
    pending_http_commands: Dict[str, List[Dict[str, Any]]],
    redis_client,
    redis_channel: str,
):
    """Unlock a machine for the given client. Returns result dict."""
    res = await db.unlock_by_client_db(machine_id, client_id)
    if res.get("error"):
        return res

    # Notify device
    payload = {"type": "unlock"}
    try:
        pending_http_commands.setdefault(machine_id, []).append(payload)
        ws = connected_machines.get(machine_id)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
                if res.get("new_display_code"):
                    await ws.send_text(
                        json.dumps(
                            {"type": "display_code", "value": res.get("new_display_code")}
                        )
                    )
            except Exception:
                pass
        if redis_client:
            try:
                await redis_client.publish(
                    redis_channel,
                    json.dumps({"machine_id": machine_id, "payload": payload}),
                )
            except Exception:
                pass
    except Exception:
        pass

    return res


async def update_stock(
    machine_id: str,
    new_stock: int,
    connected_machines: dict,
    redis_client,
    redis_channel: str,
):
    """Update machine stock and notify the device. Returns updated stock data or None."""
    result = await db.update_machine_stock(machine_id, new_stock)
    if result is None:
        return None

    payload = {"type": "stock_update", "stock": new_stock}
    try:
        ws = connected_machines.get(machine_id)
        if ws:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception as e:
                print("Failed to send WS stock_update to local client:", e)
        if redis_client:
            try:
                await redis_client.publish(
                    redis_channel,
                    json.dumps({"machine_id": machine_id, "payload": payload}),
                )
            except Exception as e:
                print("Failed to publish stock_update to redis:", e)
    except Exception:
        pass

    return result
