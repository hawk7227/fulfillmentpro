"""FulfillmentPro wrapper that adds live bridge routes without modifying backend.py."""
from __future__ import annotations

import json
import os
import time
from typing import Any

import requests
from flask import Response, jsonify, request, stream_with_context

import backend

app = backend.app

DROPSHIPPING_PLATFORM_URL = os.getenv(
    "DROPSHIPPING_PLATFORM_URL",
    "https://dropshipping-management-ten.vercel.app",
).rstrip("/")
BRIDGE_SHARED_SECRET = os.getenv("BRIDGE_SHARED_SECRET", "")


def _platform_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if BRIDGE_SHARED_SECRET:
        headers["X-Bridge-Secret"] = BRIDGE_SHARED_SECRET
    return headers


def _platform_status() -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = requests.get(
            f"{DROPSHIPPING_PLATFORM_URL}/api/live-bridge?probe=1",
            headers=_platform_headers(),
            timeout=8,
        )
        payload = response.json() if response.content else {}
        return {
            "online": response.ok,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "detail": (
                "Command Center reachable"
                if response.ok
                else f"HTTP {response.status_code}"
            ),
            "payload": payload,
        }
    except requests.RequestException as exc:
        return {
            "online": False,
            "latency_ms": None,
            "detail": str(exc),
            "payload": {},
        }


@app.get("/api/integrations/live")
def integration_live_status():
    conn = backend.get_db()
    try:
        worker = backend.worker_snapshot(conn)
    finally:
        conn.close()

    shopify_connected = bool(
        backend.get_shopify_access_token(backend.SHOPIFY_STORE_DOMAIN)
    )
    platform = _platform_status()

    connections = [
        {
            "id": "fulfillmentpro",
            "label": "FulfillmentPro Dashboard",
            "online": True,
            "detail": request.host,
        },
        {
            "id": "dropship-pro",
            "label": "Dropship Pro Command Center",
            "online": platform["online"],
            "detail": platform["detail"],
            "latency_ms": platform["latency_ms"],
        },
        {
            "id": "shopify",
            "label": "Shopify",
            "online": shopify_connected,
            "detail": backend.SHOPIFY_STORE_DOMAIN or "Not configured",
        },
        {
            "id": "worker",
            "label": "Fulfillment Bot",
            "online": bool(worker.get("worker_online")),
            "detail": worker.get("last_action") or "No recent heartbeat",
        },
    ]

    return jsonify(
        {
            "ok": all(item["online"] for item in connections),
            "connections": connections,
            "checked_at": backend.utcnow(),
        }
    )


@app.post("/api/integrations/sync-progress")
@backend.require_dashboard_auth
def integration_sync_progress():
    @stream_with_context
    def generate():
        def event(progress: int, stage: str, message: str, **extra: Any) -> str:
            return json.dumps(
                {
                    "progress": progress,
                    "stage": stage,
                    "message": message,
                    **extra,
                }
            ) + "\n"

        try:
            yield event(3, "starting", "Checking Shopify and connected systems…")
            yield event(12, "shopify", "Downloading current Shopify orders…")

            result = backend.sync_shopify_orders(max_pages=25)

            yield event(
                78,
                "orders-complete",
                (
                    f"Orders synced: {result.get('imported', 0)} imported, "
                    f"{result.get('updated', 0)} updated"
                ),
            )

            platform = _platform_status()
            yield event(
                92,
                "bridge-check",
                (
                    "Dropship Pro connection verified"
                    if platform["online"]
                    else "Dropship Pro is currently unreachable"
                ),
            )

            yield event(
                100,
                "complete",
                "FulfillmentPro synchronization completed.",
                done=True,
                result=result,
            )
        except Exception as exc:  # noqa: BLE001
            app.logger.exception("Live bridge sync failed")
            yield event(
                100,
                "failed",
                str(exc),
                done=True,
                error="sync_failed",
            )

    return Response(
        generate(),
        mimetype="application/x-ndjson",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/integrations/cron", methods=["GET", "PATCH"])
@backend.require_dashboard_auth
def integration_cron_jobs():
    target = f"{DROPSHIPPING_PLATFORM_URL}/api/live-bridge/cron"

    try:
        if request.method == "GET":
            response = requests.get(
                target,
                headers=_platform_headers(),
                timeout=15,
            )
        else:
            response = requests.patch(
                target,
                headers=_platform_headers(),
                json=request.get_json(silent=True) or {},
                timeout=20,
            )

        payload = response.json() if response.content else {}
        return jsonify(payload), response.status_code
    except requests.RequestException as exc:
        return jsonify(
            {
                "success": False,
                "error": f"Cron bridge request failed: {exc}",
            }
        ), 502
