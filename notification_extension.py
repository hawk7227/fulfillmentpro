"""Persistent live notifications for FulfillmentPro.

This module extends the existing Flask app without changing backend.py. It keeps the
old dashboard notification design while making order and worker events durable.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from flask import jsonify, request

import backend

app = backend.app

EVENTS: dict[str, dict[str, Any]] = {
    "order_placed": {"severity": "critical", "title": "New order received", "attention": True, "href": "/orders.html"},
    "order_cancelled": {"severity": "warning", "title": "Order cancelled", "attention": True, "href": "/orders.html"},
    "fulfillment_started": {"severity": "info", "title": "Fulfillment started", "attention": False, "href": "/queue.html"},
    "verification_required": {"severity": "warning", "title": "Worker verification required", "attention": True, "href": "/queue.html"},
    "mapping_required": {"severity": "warning", "title": "Product mapping required", "attention": True, "href": "/mapping.html"},
    "fulfillment_succeeded": {"severity": "success", "title": "Fulfillment successful", "attention": False, "href": "/orders.html"},
    "fulfillment_failed": {"severity": "critical", "title": "Fulfillment failed", "attention": True, "href": "/queue.html"},
    "payment_failed": {"severity": "critical", "title": "Supplier payment failed", "attention": True, "href": "/queue.html"},
    "tracking_added": {"severity": "success", "title": "Tracking added", "attention": False, "href": "/orders.html"},
    "tracking_failed": {"severity": "warning", "title": "Tracking update failed", "attention": True, "href": "/queue.html"},
    "retry_scheduled": {"severity": "info", "title": "Fulfillment retry scheduled", "attention": False, "href": "/queue.html"},
    "worker_offline": {"severity": "critical", "title": "Fulfillment worker offline", "attention": True, "href": "/queue.html"},
}


def _init() -> None:
    conn = backend.get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notification_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_key TEXT NOT NULL UNIQUE,
          event_type TEXT NOT NULL,
          severity TEXT NOT NULL DEFAULT 'info',
          title TEXT NOT NULL,
          message TEXT NOT NULL,
          order_id INTEGER,
          task_id INTEGER,
          href TEXT,
          metadata TEXT NOT NULL DEFAULT '{}',
          requires_attention INTEGER NOT NULL DEFAULT 0,
          read_at TEXT,
          resolved_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_notification_events_created ON notification_events(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_notification_events_unread ON notification_events(read_at,resolved_at,created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_notification_events_order ON notification_events(order_id,created_at DESC);
        """
    )
    conn.commit()
    conn.close()


def emit(event_type: str, *, event_key: str | None = None, order_id: int | None = None,
         task_id: int | None = None, title: str | None = None, message: str | None = None,
         metadata: dict[str, Any] | None = None, resolve_order: bool = False) -> None:
    spec = EVENTS.get(event_type, {"severity": "info", "title": "Fulfillment update", "attention": False, "href": "/queue.html"})
    payload = metadata or {}
    key = event_key or hashlib.sha256(json.dumps({"type": event_type, "order": order_id, "task": task_id, "payload": payload}, sort_keys=True, default=str).encode()).hexdigest()
    now = backend.utcnow()
    conn = backend.get_db()
    conn.execute(
        """INSERT INTO notification_events(event_key,event_type,severity,title,message,order_id,task_id,href,metadata,requires_attention,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(event_key) DO UPDATE SET title=excluded.title,message=excluded.message,metadata=excluded.metadata,updated_at=excluded.updated_at""",
        (key, event_type, spec["severity"], title or spec["title"], message or spec["title"], order_id, task_id,
         f"{spec['href']}{'?order='+str(order_id) if order_id else ''}", json.dumps(payload, default=str), int(spec["attention"]), now, now),
    )
    if resolve_order and order_id:
        conn.execute("UPDATE notification_events SET resolved_at=?,updated_at=? WHERE order_id=? AND event_type='order_placed' AND resolved_at IS NULL", (now, now, order_id))
    conn.commit()
    conn.close()


def _order_context(conn, order_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT id,shopify_order_number,customer_name,current_total_price,total_price,currency,item_count,created_at,fulfillment_status,cancelled_at FROM orders WHERE id=?", (order_id,)).fetchone()
    return dict(row) if row else {"id": order_id}


_original_upsert_order = backend.upsert_order


def _upsert_order_with_notifications(conn, order: dict[str, Any], create_tasks: bool = True):
    order_id, created = _original_upsert_order(conn, order, create_tasks=create_tasks)
    context = _order_context(conn, order_id)
    if created:
        emit("order_placed", event_key=f"order:{order.get('shopify_order_id')}:created", order_id=order_id,
             message=f"Order #{context.get('shopify_order_number') or order_id} from {context.get('customer_name') or 'Customer'} was received.", metadata=context)
    elif order.get("cancelled_at"):
        emit("order_cancelled", event_key=f"order:{order.get('shopify_order_id')}:cancelled", order_id=order_id,
             message=f"Order #{context.get('shopify_order_number') or order_id} was cancelled.", metadata=context, resolve_order=True)
    elif str(order.get("fulfillment_status") or "").upper() in {"FULFILLED", "SUCCESS"}:
        emit("fulfillment_succeeded", event_key=f"order:{order.get('shopify_order_id')}:fulfilled", order_id=order_id,
             message=f"Order #{context.get('shopify_order_number') or order_id} was fulfilled successfully.", metadata=context, resolve_order=True)
    return order_id, created


backend.upsert_order = _upsert_order_with_notifications


def _task_event(state: str, body: dict[str, Any], task_id: int) -> tuple[str, bool] | None:
    normalized = state.lower()
    if normalized == "verification_required": return "verification_required", False
    if normalized == "needs_mapping": return "mapping_required", False
    if normalized == "purchased": return "fulfillment_succeeded", True
    if normalized == "failed":
        text = f"{body.get('error_message','')} {body.get('last_action','')}".lower()
        if "payment" in text: return "payment_failed", False
        if "tracking" in text: return "tracking_failed", False
        return "fulfillment_failed", False
    if normalized.startswith("processing"): return "fulfillment_started", False
    if normalized in {"retry", "retry_scheduled"}: return "retry_scheduled", False
    return None


@app.after_request
def capture_worker_notification(response):
    match = re.fullmatch(r"/api/queue/(\d+)/update", request.path)
    if match and request.method == "POST" and response.status_code < 400:
        body = request.get_json(silent=True) or {}
        state = str(body.get("state") or "")
        task_id = int(match.group(1))
        event = _task_event(state, body, task_id)
        if event:
            conn = backend.get_db()
            row = conn.execute("SELECT t.order_id,o.shopify_order_number,li.title product_name FROM tasks t LEFT JOIN orders o ON o.id=t.order_id LEFT JOIN line_items li ON li.id=t.line_item_id WHERE t.id=?", (task_id,)).fetchone()
            conn.close()
            context = dict(row) if row else {}
            event_type, resolve = event
            emit(event_type, event_key=f"task:{task_id}:{state}:{body.get('amazon_order_id') or body.get('last_action') or ''}",
                 order_id=context.get("order_id"), task_id=task_id,
                 message=body.get("error_message") or body.get("last_action") or f"{EVENTS[event_type]['title']} for order #{context.get('shopify_order_number') or context.get('order_id') or ''}.",
                 metadata={**context, **body}, resolve_order=resolve)
    return response


@app.get("/api/notifications/events")
@backend.require_dashboard_auth
def notification_events():
    limit = min(max(int(request.args.get("limit", 50)), 1), 200)
    since = request.args.get("since")
    conn = backend.get_db()
    sql = "SELECT * FROM notification_events"
    params: list[Any] = []
    if since:
        sql += " WHERE created_at>?"
        params.append(since)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = [dict(row) for row in conn.execute(sql, params)]
    summary = dict(conn.execute("""SELECT COUNT(*) FILTER (WHERE read_at IS NULL AND resolved_at IS NULL) unread_total,
      COUNT(*) FILTER (WHERE event_type='order_placed' AND read_at IS NULL AND resolved_at IS NULL) unread_new_orders,
      COUNT(*) FILTER (WHERE severity='critical' AND resolved_at IS NULL) open_critical,
      MAX(created_at) latest_event_at FROM notification_events""").fetchone())
    conn.close()
    for row in rows:
        try: row["metadata"] = json.loads(row.get("metadata") or "{}")
        except ValueError: row["metadata"] = {}
    return jsonify({"events": rows, "summary": summary})


@app.post("/api/notifications/events/action")
@backend.require_dashboard_auth
def notification_action():
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    now = backend.utcnow()
    conn = backend.get_db()
    if action == "mark_read" and body.get("id"):
        conn.execute("UPDATE notification_events SET read_at=?,updated_at=? WHERE id=?", (now, now, body["id"]))
    elif action == "mark_order_read" and body.get("order_id"):
        conn.execute("UPDATE notification_events SET read_at=?,updated_at=? WHERE order_id=? AND event_type='order_placed' AND read_at IS NULL", (now, now, body["order_id"]))
    elif action == "mark_all_read":
        conn.execute("UPDATE notification_events SET read_at=?,updated_at=? WHERE read_at IS NULL", (now, now))
    else:
        conn.close()
        return jsonify({"error": "Unknown action"}), 400
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


_init()
