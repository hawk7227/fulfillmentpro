"""Automatic Shopify webhook registration and health reporting for FulfillmentPro."""
from __future__ import annotations

import json
import threading
import time
from typing import Any

from flask import jsonify

import backend

app = backend.app

TOPICS = {
    "ORDERS_CREATE": f"{backend.SHOPIFY_WEBHOOK_BASE_URL}/webhooks/shopify/orders-create",
    "ORDERS_UPDATED": f"{backend.SHOPIFY_WEBHOOK_BASE_URL}/webhooks/shopify/orders-updated",
    "ORDERS_CANCELLED": f"{backend.SHOPIFY_WEBHOOK_BASE_URL}/webhooks/shopify/orders-cancelled",
}


def _init_table() -> None:
    conn = backend.get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS webhook_registration_status (
          id INTEGER PRIMARY KEY CHECK(id=1),
          status TEXT NOT NULL DEFAULT 'pending',
          last_attempt_at TEXT,
          last_success_at TEXT,
          callback_base_url TEXT,
          registered_topics TEXT NOT NULL DEFAULT '[]',
          errors TEXT NOT NULL DEFAULT '[]',
          updated_at TEXT NOT NULL
        );
        INSERT OR IGNORE INTO webhook_registration_status(id,status,updated_at)
        VALUES(1,'pending',datetime('now'));
        """
    )
    conn.commit()
    conn.close()


def _save(status: str, registered: list[dict[str, Any]], errors: list[dict[str, Any]]) -> None:
    now = backend.utcnow()
    conn = backend.get_db()
    conn.execute(
        """
        UPDATE webhook_registration_status
        SET status=?, last_attempt_at=?,
            last_success_at=CASE WHEN ?='ready' THEN ? ELSE last_success_at END,
            callback_base_url=?, registered_topics=?, errors=?, updated_at=?
        WHERE id=1
        """,
        (
            status,
            now,
            status,
            now,
            backend.SHOPIFY_WEBHOOK_BASE_URL,
            json.dumps(registered),
            json.dumps(errors),
            now,
        ),
    )
    conn.commit()
    conn.close()


def ensure_webhooks() -> dict[str, Any]:
    if not backend.SHOPIFY_STORE_DOMAIN or not backend.get_shopify_access_token(backend.SHOPIFY_STORE_DOMAIN):
        errors = [{"message": "Shopify is not connected"}]
        _save("blocked", [], errors)
        return {"ok": False, "registered": [], "errors": errors}

    query = """query ExistingWebhookSubscriptions($first:Int!){webhookSubscriptions(first:$first){nodes{id topic endpoint{... on WebhookHttpEndpoint{callbackUrl}}}}}"""
    mutation = """mutation CreateWebhook($topic:WebhookSubscriptionTopic!,$callbackUrl:URL!){webhookSubscriptionCreate(topic:$topic,webhookSubscription:{callbackUrl:$callbackUrl,format:JSON}){webhookSubscription{id topic} userErrors{field message}}}"""

    try:
        nodes = backend.shopify_graphql(query, {"first": 100}).get("webhookSubscriptions", {}).get("nodes", [])
    except Exception as exc:  # noqa: BLE001
        errors = [{"message": str(exc)}]
        _save("failed", [], errors)
        return {"ok": False, "registered": [], "errors": errors}

    existing = {
        (str(node.get("topic") or ""), str((node.get("endpoint") or {}).get("callbackUrl") or ""))
        for node in nodes
    }
    registered: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for topic, callback_url in TOPICS.items():
        if (topic, callback_url) in existing:
            registered.append({"topic": topic, "callback_url": callback_url, "status": "existing"})
            continue
        try:
            result = backend.shopify_graphql(mutation, {"topic": topic, "callbackUrl": callback_url}).get("webhookSubscriptionCreate") or {}
            user_errors = result.get("userErrors") or []
            if user_errors:
                errors.append({"topic": topic, "callback_url": callback_url, "errors": user_errors})
            else:
                registered.append({"topic": topic, "callback_url": callback_url, "status": "created"})
        except Exception as exc:  # noqa: BLE001
            errors.append({"topic": topic, "callback_url": callback_url, "errors": [{"message": str(exc)}]})

    _save("ready" if not errors else "partial", registered, errors)
    return {"ok": not errors, "registered": registered, "errors": errors}


def _startup_worker() -> None:
    # Delay until Gunicorn has completed application import and Railway networking is ready.
    time.sleep(4)
    try:
        ensure_webhooks()
    except Exception:  # noqa: BLE001
        app.logger.exception("Automatic Shopify webhook registration failed")


@app.get("/api/shopify/webhooks/status")
@backend.require_dashboard_auth
def webhook_status():
    conn = backend.get_db()
    row = conn.execute("SELECT * FROM webhook_registration_status WHERE id=1").fetchone()
    conn.close()
    data = dict(row) if row else {"status": "unknown"}
    for key in ("registered_topics", "errors"):
        try:
            data[key] = json.loads(data.get(key) or "[]")
        except (TypeError, ValueError):
            data[key] = []
    return jsonify(data)


@app.post("/api/shopify/webhooks/ensure-live")
@backend.require_dashboard_auth
def ensure_live_webhooks():
    result = ensure_webhooks()
    return jsonify(result), (200 if result["ok"] else 207)


_init_table()
threading.Thread(target=_startup_worker, name="shopify-webhook-registration", daemon=True).start()
