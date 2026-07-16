"""FulfillmentPro backend with Shopify synchronization and owner dashboard."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from typing import Any
from urllib.parse import urlencode

import requests
from flask import Flask, jsonify, make_response, redirect, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app, resources={r"/api/*": {"origins": os.getenv("DASHBOARD_ALLOWED_ORIGIN", "*")}})

DATABASE_PATH = os.getenv("DATABASE_PATH", "fulfillment.db")
WORKER_AUTH_TOKEN = os.getenv("WORKER_AUTH_TOKEN", "")
DASHBOARD_AUTH_TOKEN = os.getenv("DASHBOARD_AUTH_TOKEN", "") or WORKER_AUTH_TOKEN
SHOPIFY_WEBHOOK_SECRET = os.getenv("SHOPIFY_WEBHOOK_SECRET", "")
SHOPIFY_STORE_DOMAIN = os.getenv("SHOPIFY_STORE_DOMAIN", "").replace("https://", "").replace("http://", "").rstrip("/")
SHOPIFY_ADMIN_ACCESS_TOKEN = os.getenv("SHOPIFY_ADMIN_ACCESS_TOKEN", "")
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2025-10")
WORKER_OFFLINE_THRESHOLD = int(os.getenv("WORKER_OFFLINE_THRESHOLD", "120"))
SHOPIFY_SCOPES = os.getenv("SHOPIFY_SCOPES", "read_orders,read_products,read_customers,read_fulfillments,read_inventory,read_locations")
SHOPIFY_REDIRECT_URI = os.getenv("SHOPIFY_REDIRECT_URI", "https://fulfillmentpro.up.railway.app/shopify/callback")

ORDER_COLUMNS = {
    "financial_status": "TEXT", "fulfillment_status": "TEXT", "delivery_status": "TEXT",
    "source_name": "TEXT", "currency": "TEXT", "subtotal_price": "REAL DEFAULT 0",
    "current_total_price": "REAL DEFAULT 0", "refunds_total": "REAL DEFAULT 0",
    "cancelled_at": "TEXT", "closed_at": "TEXT", "processed_at": "TEXT",
    "shipping_method": "TEXT", "tracking_company": "TEXT", "tracking_number": "TEXT",
    "tracking_url": "TEXT", "tags": "TEXT DEFAULT '[]'", "item_count": "INTEGER DEFAULT 0",
    "shopify_updated_at": "TEXT", "synced_at": "TEXT"
}
LINE_ITEM_COLUMNS = {
    "shopify_product_id": "TEXT", "shopify_variant_id": "TEXT", "image_url": "TEXT", "vendor": "TEXT"
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def add_missing_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def init_db() -> None:
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS orders (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      shopify_order_id TEXT UNIQUE NOT NULL,
      shopify_order_number TEXT,
      customer_name TEXT,
      customer_email TEXT,
      shipping_address TEXT,
      total_price REAL DEFAULT 0,
      created_at TEXT,
      updated_at TEXT
    );
    CREATE TABLE IF NOT EXISTS line_items (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      order_id INTEGER NOT NULL,
      shopify_line_item_id TEXT,
      title TEXT,
      variant_title TEXT,
      sku TEXT,
      quantity INTEGER DEFAULT 1,
      price REAL DEFAULT 0,
      FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
      UNIQUE(order_id, shopify_line_item_id)
    );
    CREATE TABLE IF NOT EXISTS tasks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      unique_key TEXT UNIQUE NOT NULL,
      order_id INTEGER,
      line_item_id INTEGER,
      asin TEXT,
      amazon_url TEXT,
      quantity INTEGER DEFAULT 1,
      state TEXT DEFAULT 'queued',
      amazon_order_id TEXT,
      error_message TEXT,
      created_at TEXT,
      updated_at TEXT,
      last_action TEXT,
      FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE,
      FOREIGN KEY(line_item_id) REFERENCES line_items(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS worker_status (
      id INTEGER PRIMARY KEY CHECK(id=1), is_online INTEGER DEFAULT 0,
      last_heartbeat_at TEXT, last_error TEXT, last_action TEXT, last_offline_notification_at TEXT
    );
    CREATE TABLE IF NOT EXISTS push_tokens (
      id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT UNIQUE NOT NULL, device_label TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS products (
      id INTEGER PRIMARY KEY AUTOINCREMENT, sku TEXT UNIQUE NOT NULL, asin TEXT NOT NULL,
      amazon_url TEXT NOT NULL, product_name TEXT, buy_price REAL, sell_price REAL,
      category TEXT, is_active INTEGER DEFAULT 1, stock_status TEXT, notes TEXT
    );
    CREATE TABLE IF NOT EXISTS sync_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, started_at TEXT NOT NULL,
      completed_at TEXT, status TEXT NOT NULL, imported INTEGER DEFAULT 0, updated INTEGER DEFAULT 0,
      error_message TEXT
    );
    CREATE TABLE IF NOT EXISTS shopify_connections (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      shop_domain TEXT UNIQUE NOT NULL,
      access_token TEXT NOT NULL,
      granted_scopes TEXT,
      installed_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state, created_at);
    CREATE INDEX IF NOT EXISTS idx_line_items_order ON line_items(order_id);
    INSERT OR IGNORE INTO worker_status(id,is_online) VALUES(1,0);
    """)
    add_missing_columns(conn, "orders", ORDER_COLUMNS)
    add_missing_columns(conn, "line_items", LINE_ITEM_COLUMNS)
    conn.commit()
    conn.close()


init_db()


def is_local_request() -> bool:
    return request.remote_addr in {"127.0.0.1", "::1"}


def require_dashboard_auth(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not DASHBOARD_AUTH_TOKEN:
            if is_local_request():
                return fn(*args, **kwargs)
            return jsonify({"error": "DASHBOARD_AUTH_TOKEN is not configured"}), 503
        if not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {DASHBOARD_AUTH_TOKEN}"):
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapped


def require_worker_auth(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not WORKER_AUTH_TOKEN:
            return jsonify({"error": "WORKER_AUTH_TOKEN is not configured"}), 503
        if not hmac.compare_digest(request.headers.get("Authorization", ""), f"Bearer {WORKER_AUTH_TOKEN}"):
            return jsonify({"error": "Unauthorized"}), 401
        return fn(*args, **kwargs)
    return wrapped


def is_valid_shop_domain(shop: str | None) -> bool:
    value = str(shop or "").strip().lower()
    if not value.endswith(".myshopify.com"):
        return False
    prefix = value[:-len(".myshopify.com")]
    return bool(prefix) and all(ch.isalnum() or ch == "-" for ch in prefix)


def verify_shopify_oauth_hmac(args) -> bool:
    if not SHOPIFY_CLIENT_SECRET:
        return False
    received = str(args.get("hmac") or "")
    if not received:
        return False
    pairs: list[str] = []
    for key in sorted(args.keys()):
        if key in {"hmac", "signature"}:
            continue
        values = args.getlist(key) if hasattr(args, "getlist") else [args.get(key)]
        for value in values:
            pairs.append(f"{key}={value}")
    message = "&".join(pairs)
    calculated = hmac.new(SHOPIFY_CLIENT_SECRET.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calculated, received)


def save_shopify_connection(shop: str, access_token: str, granted_scopes: str = "") -> None:
    now = utcnow()
    conn = get_db()
    conn.execute("""INSERT INTO shopify_connections(shop_domain,access_token,granted_scopes,installed_at,updated_at)
      VALUES(?,?,?,?,?) ON CONFLICT(shop_domain) DO UPDATE SET access_token=excluded.access_token,granted_scopes=excluded.granted_scopes,updated_at=excluded.updated_at""",
      (shop.lower(), access_token, granted_scopes, now, now))
    conn.commit()
    conn.close()


def get_shopify_connection(shop: str | None = None) -> dict[str, Any] | None:
    target = str(shop or SHOPIFY_STORE_DOMAIN or "").strip().lower()
    if not target:
        return None
    conn = get_db()
    row = conn.execute("SELECT shop_domain,access_token,granted_scopes,installed_at,updated_at FROM shopify_connections WHERE shop_domain=? LIMIT 1", (target,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_shopify_access_token(shop: str | None = None) -> str:
    connection = get_shopify_connection(shop)
    if connection and connection.get("access_token"):
        return str(connection["access_token"])
    return SHOPIFY_ADMIN_ACCESS_TOKEN


def verify_shopify_webhook(raw: bytes, header: str) -> bool:
    if not SHOPIFY_WEBHOOK_SECRET:
        return os.getenv("FLASK_ENV") == "development" and is_local_request()
    digest = base64.b64encode(hmac.new(SHOPIFY_WEBHOOK_SECRET.encode(), raw, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(digest, header or "")


def money(node: Any, key: str) -> tuple[float, str]:
    payload = ((node or {}).get(key) or {}).get("shopMoney") or {}
    try:
        amount = float(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return amount, str(payload.get("currencyCode") or "USD")


def shipping_name(address: dict[str, Any]) -> str:
    return " ".join(filter(None, [address.get("firstName") or address.get("first_name"), address.get("lastName") or address.get("last_name")])).strip()


def normalize_rest_order(order: dict[str, Any]) -> dict[str, Any]:
    address = order.get("shipping_address") or {}
    fulfillments = order.get("fulfillments") or []
    tracking = fulfillments[-1] if fulfillments else {}
    line_items = order.get("line_items") or []
    return {
      "shopify_order_id": str(order.get("id")), "shopify_order_number": str(order.get("order_number") or order.get("name") or ""),
      "customer_name": shipping_name(address), "customer_email": order.get("email"), "shipping_address": json.dumps(address),
      "total_price": float(order.get("current_total_price") or order.get("total_price") or 0),
      "subtotal_price": float(order.get("current_subtotal_price") or order.get("subtotal_price") or 0),
      "current_total_price": float(order.get("current_total_price") or order.get("total_price") or 0),
      "refunds_total": 0.0, "currency": order.get("currency") or "USD", "created_at": order.get("created_at") or utcnow(),
      "updated_at": utcnow(), "shopify_updated_at": order.get("updated_at"), "processed_at": order.get("processed_at"),
      "cancelled_at": order.get("cancelled_at"), "closed_at": order.get("closed_at"),
      "financial_status": str(order.get("financial_status") or "UNKNOWN").upper(),
      "fulfillment_status": str(order.get("fulfillment_status") or "UNFULFILLED").upper(),
      "delivery_status": "DELIVERED" if any(str(f.get("shipment_status") or "").lower() == "delivered" for f in fulfillments) else None,
      "source_name": order.get("source_name"), "shipping_method": ((order.get("shipping_lines") or [{}])[0]).get("title"),
      "tracking_company": tracking.get("tracking_company"), "tracking_number": tracking.get("tracking_number"),
      "tracking_url": tracking.get("tracking_url"), "tags": json.dumps(order.get("tags") or []),
      "item_count": sum(int(i.get("quantity") or 0) for i in line_items), "synced_at": utcnow(), "line_items": line_items
    }


def normalize_graphql_order(node: dict[str, Any]) -> dict[str, Any]:
    address = node.get("shippingAddress") or {}
    total, currency = money(node, "currentTotalPriceSet")
    subtotal, _ = money(node, "currentSubtotalPriceSet")
    refunded, _ = money(node, "totalRefundedSet")
    fulfills = node.get("fulfillments") or []
    info = ((fulfills[-1].get("trackingInfo") or [None])[0] if fulfills else None) or {}
    lines = ((node.get("lineItems") or {}).get("nodes") or [])
    return {
      "shopify_order_id": str(node.get("legacyResourceId") or node.get("id")), "shopify_order_number": str(node.get("name") or "").lstrip("#"),
      "customer_name": ((node.get("customer") or {}).get("displayName") or shipping_name(address)), "customer_email": node.get("email"),
      "shipping_address": json.dumps(address), "total_price": total, "subtotal_price": subtotal, "current_total_price": total,
      "refunds_total": refunded, "currency": currency, "created_at": node.get("createdAt") or utcnow(), "updated_at": utcnow(),
      "shopify_updated_at": node.get("updatedAt"), "processed_at": node.get("processedAt"), "cancelled_at": node.get("cancelledAt"),
      "closed_at": node.get("closedAt"), "financial_status": str(node.get("displayFinancialStatus") or "UNKNOWN"),
      "fulfillment_status": str(node.get("displayFulfillmentStatus") or "UNFULFILLED"), "delivery_status": None,
      "source_name": node.get("sourceName"), "shipping_method": (node.get("shippingLine") or {}).get("title"),
      "tracking_company": info.get("company"), "tracking_number": info.get("number"), "tracking_url": info.get("url"),
      "tags": json.dumps(node.get("tags") or []), "item_count": sum(int(i.get("quantity") or 0) for i in lines),
      "synced_at": utcnow(), "line_items": lines
    }


def upsert_order(conn: sqlite3.Connection, order: dict[str, Any], create_tasks: bool = True) -> tuple[int, bool]:
    existing = conn.execute("SELECT id FROM orders WHERE shopify_order_id=?", (order["shopify_order_id"],)).fetchone()
    fields = [k for k in order if k != "line_items"]
    if existing:
        order_id = int(existing["id"])
        editable = [f for f in fields if f != "shopify_order_id"]
        conn.execute("UPDATE orders SET " + ",".join(f"{f}=?" for f in editable) + " WHERE id=?", [order[f] for f in editable] + [order_id])
        created = False
    else:
        conn.execute(f"INSERT INTO orders({','.join(fields)}) VALUES({','.join('?' for _ in fields)})", [order[f] for f in fields])
        order_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        created = True
    products = {r["sku"]: dict(r) for r in conn.execute("SELECT * FROM products WHERE is_active=1")}
    for idx, item in enumerate(order.get("line_items") or []):
        item_id = str(item.get("legacyResourceId") or item.get("id") or idx)
        price = item.get("price")
        if price is None:
            price, _ = money(item, "originalUnitPriceSet")
        product = item.get("product") or {}
        variant = item.get("variant") or {}
        image = item.get("image") or {}
        values = (order_id, item_id, item.get("title"), item.get("variant_title") or item.get("variantTitle"), item.get("sku"), int(item.get("quantity") or 1), float(price or 0), str(product.get("id") or ""), str(variant.get("id") or ""), image.get("url"), product.get("vendor"))
        conn.execute("""INSERT INTO line_items(order_id,shopify_line_item_id,title,variant_title,sku,quantity,price,shopify_product_id,shopify_variant_id,image_url,vendor)
          VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(order_id,shopify_line_item_id) DO UPDATE SET title=excluded.title,variant_title=excluded.variant_title,sku=excluded.sku,quantity=excluded.quantity,price=excluded.price,shopify_product_id=excluded.shopify_product_id,shopify_variant_id=excluded.shopify_variant_id,image_url=excluded.image_url,vendor=excluded.vendor""", values)
        line_id = conn.execute("SELECT id FROM line_items WHERE order_id=? AND shopify_line_item_id=?", (order_id, item_id)).fetchone()[0]
        if create_tasks:
            sku = str(item.get("sku") or "").strip()
            mapped = products.get(sku)
            state = "queued" if mapped else "needs_mapping"
            error = None if mapped else ("No SKU provided" if not sku else f"ASIN {sku} not in catalog")
            conn.execute("""INSERT OR IGNORE INTO tasks(unique_key,order_id,line_item_id,asin,amazon_url,quantity,state,error_message,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?)""", (f'{order["shopify_order_id"]}:{item_id}', order_id, line_id, sku or None, mapped.get("amazon_url") if mapped else None, int(item.get("quantity") or 1), state, error, utcnow(), utcnow()))
    return order_id, created


SHOPIFY_QUERY = """query Orders($cursor:String,$query:String){orders(first:100,after:$cursor,reverse:true,sortKey:CREATED_AT,query:$query){pageInfo{hasNextPage endCursor}nodes{id legacyResourceId name createdAt updatedAt processedAt cancelledAt closedAt email displayFinancialStatus displayFulfillmentStatus sourceName tags currentTotalPriceSet{shopMoney{amount currencyCode}} currentSubtotalPriceSet{shopMoney{amount currencyCode}} totalRefundedSet{shopMoney{amount currencyCode}} customer{displayName} shippingAddress{firstName lastName address1 address2 city province provinceCode zip country countryCodeV2 phone} shippingLine{title} lineItems(first:50){nodes{id title variantTitle sku quantity originalUnitPriceSet{shopMoney{amount currencyCode}} image{url altText} product{id title vendor} variant{id title}}} fulfillments{status trackingInfo{company number url}}}}}"""


def shopify_graphql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    access_token = get_shopify_access_token(SHOPIFY_STORE_DOMAIN)
    if not SHOPIFY_STORE_DOMAIN or not access_token:
        raise RuntimeError("Shopify is not connected. Complete OAuth installation or configure SHOPIFY_ADMIN_ACCESS_TOKEN.")
    url = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    response = requests.post(url, headers={"X-Shopify-Access-Token": access_token, "Content-Type": "application/json"}, json={"query": query, "variables": variables}, timeout=45)
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise RuntimeError(payload["errors"][0].get("message", "Shopify GraphQL error"))
    return payload["data"]


def sync_shopify_orders(search_query: str | None = None, max_pages: int = 25) -> dict[str, Any]:
    conn = get_db()
    run_id = conn.execute("INSERT INTO sync_runs(source,started_at,status) VALUES('shopify',?,'running')", (utcnow(),)).lastrowid
    conn.commit()
    imported = updated = pages = 0
    cursor = None
    try:
        while pages < max_pages:
            connection = shopify_graphql(SHOPIFY_QUERY, {"cursor": cursor, "query": search_query})["orders"]
            for node in connection["nodes"]:
                _, created = upsert_order(conn, normalize_graphql_order(node), create_tasks=True)
                imported += int(created)
                updated += int(not created)
            conn.commit()
            pages += 1
            if not connection["pageInfo"]["hasNextPage"]:
                break
            cursor = connection["pageInfo"]["endCursor"]
        conn.execute("UPDATE sync_runs SET completed_at=?,status='success',imported=?,updated=? WHERE id=?", (utcnow(), imported, updated, run_id))
        conn.commit()
        return {"status": "success", "imported": imported, "updated": updated, "pages": pages}
    except Exception as exc:
        conn.rollback()
        conn.execute("UPDATE sync_runs SET completed_at=?,status='failed',error_message=? WHERE id=?", (utcnow(), str(exc)[:1000], run_id))
        conn.commit()
        raise
    finally:
        conn.close()


def worker_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    row = dict(conn.execute("SELECT * FROM worker_status WHERE id=1").fetchone())
    online = False
    if row.get("last_heartbeat_at"):
        try:
            online = (datetime.now(timezone.utc) - datetime.fromisoformat(row["last_heartbeat_at"].replace("Z", "+00:00"))).total_seconds() < WORKER_OFFLINE_THRESHOLD
        except ValueError:
            pass
    return {**row, "worker_online": online}


@app.get("/health")
def health():
    return jsonify({"status": "healthy", "shopify_configured": bool(SHOPIFY_STORE_DOMAIN and get_shopify_access_token(SHOPIFY_STORE_DOMAIN)), "timestamp": utcnow()})


@app.post("/api/auth/check")
@require_dashboard_auth
def auth_check():
    return jsonify({"ok": True})


@app.get("/api/dashboard")
@require_dashboard_auth
def dashboard():
    conn = get_db()
    today = datetime.now(timezone.utc).date().isoformat()
    counts = {r["state"]: r["count"] for r in conn.execute("SELECT state,COUNT(*) count FROM tasks GROUP BY state")}
    row = conn.execute("""SELECT COUNT(*) total_orders, COALESCE(SUM(current_total_price),0) revenue, COALESCE(SUM(refunds_total),0) refunds,
      SUM(CASE WHEN financial_status='PAID' THEN 1 ELSE 0 END) paid_orders,
      SUM(CASE WHEN fulfillment_status IN ('FULFILLED','PARTIALLY_FULFILLED') THEN 1 ELSE 0 END) fulfilled_orders,
      SUM(CASE WHEN delivery_status='DELIVERED' THEN 1 ELSE 0 END) delivered_orders,
      SUM(CASE WHEN substr(created_at,1,10)=? THEN 1 ELSE 0 END) orders_today,
      COALESCE(SUM(CASE WHEN substr(created_at,1,10)=? THEN item_count ELSE 0 END),0) items_today FROM orders""", (today, today)).fetchone()
    recent = [dict(r) for r in conn.execute("""SELECT o.*,COUNT(t.id) total_tasks,SUM(CASE WHEN t.state='purchased' THEN 1 ELSE 0 END) purchased_tasks,
      SUM(CASE WHEN t.state='failed' THEN 1 ELSE 0 END) failed_tasks,SUM(CASE WHEN t.state='needs_mapping' THEN 1 ELSE 0 END) mapping_tasks,
      SUM(CASE WHEN t.state='verification_required' THEN 1 ELSE 0 END) verification_tasks
      FROM orders o LEFT JOIN tasks t ON t.order_id=o.id GROUP BY o.id ORDER BY o.created_at DESC LIMIT 12""")]
    tops = [dict(r) for r in conn.execute("""SELECT COALESCE(NULLIF(title,''),'Untitled product') title,MAX(image_url) image_url,SUM(quantity) units,SUM(quantity*price) revenue FROM line_items GROUP BY title ORDER BY units DESC LIMIT 5""")]
    sync = dict(conn.execute("SELECT * FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone() or {})
    worker = worker_snapshot(conn)
    conn.close()
    data = dict(row)
    data.update({"queue": counts.get("queued", 0), "needs_mapping": counts.get("needs_mapping", 0), "verification_required": counts.get("verification_required", 0), "purchased": counts.get("purchased", 0), "failed": counts.get("failed", 0), "processing": sum(v for k, v in counts.items() if k.startswith("processing")), "recent_orders": recent, "top_products": tops, "worker": worker, "last_sync": sync, "store_domain": SHOPIFY_STORE_DOMAIN, "shopify_configured": bool(SHOPIFY_STORE_DOMAIN and get_shopify_access_token(SHOPIFY_STORE_DOMAIN))})
    return jsonify(data)


@app.post("/api/shopify/sync")
@require_dashboard_auth
def sync_shopify():
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(sync_shopify_orders(str(body.get("query") or "").strip() or None, max(1, min(int(body.get("max_pages") or 25), 50))))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 502


@app.get("/api/orders")
@require_dashboard_auth
def get_orders():
    page = max(int(request.args.get("page", 1)), 1)
    per_page = min(max(int(request.args.get("per_page", 25)), 1), 100)
    search = request.args.get("search", "").strip()
    status = request.args.get("status", "").strip().upper()
    where, params = [], []
    if search:
        where.append("(o.shopify_order_number LIKE ? OR o.customer_name LIKE ? OR o.tracking_number LIKE ?)")
        params += [f"%{search}%"] * 3
    if status:
        where.append("(o.fulfillment_status=? OR o.financial_status=? OR EXISTS(SELECT 1 FROM tasks tx WHERE tx.order_id=o.id AND upper(tx.state)=?))")
        params += [status, status, status]
    clause = " WHERE " + " AND ".join(where) if where else ""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM orders o" + clause, params).fetchone()[0]
    rows = [dict(r) for r in conn.execute("""SELECT o.*,COUNT(t.id) total_tasks,SUM(CASE WHEN t.state='purchased' THEN 1 ELSE 0 END) purchased_tasks,
      SUM(CASE WHEN t.state='failed' THEN 1 ELSE 0 END) failed_tasks,SUM(CASE WHEN t.state='needs_mapping' THEN 1 ELSE 0 END) mapping_tasks,
      SUM(CASE WHEN t.state='verification_required' THEN 1 ELSE 0 END) verification_tasks
      FROM orders o LEFT JOIN tasks t ON t.order_id=o.id""" + clause + " GROUP BY o.id ORDER BY o.created_at DESC LIMIT ? OFFSET ?", params + [per_page, (page - 1) * per_page])]
    conn.close()
    return jsonify({"orders": rows, "page": page, "per_page": per_page, "total": total, "pages": max((total + per_page - 1) // per_page, 1)})


@app.get("/api/orders/<int:order_id>")
@require_dashboard_auth
def order_detail(order_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Order not found"}), 404
    order = dict(row)
    order["items"] = [dict(r) for r in conn.execute("""SELECT li.*,t.state,t.amazon_url,t.amazon_order_id,t.error_message,t.last_action,t.quantity task_quantity FROM line_items li LEFT JOIN tasks t ON t.line_item_id=li.id WHERE li.order_id=?""", (order_id,))]
    conn.close()
    return jsonify({"order": order})


@app.get("/api/status")
@require_dashboard_auth
def status():
    conn = get_db()
    worker = worker_snapshot(conn)
    counts = {r["state"]: r["count"] for r in conn.execute("SELECT state,COUNT(*) count FROM tasks GROUP BY state")}
    conn.close()
    return jsonify({**worker, "queue_size": counts.get("queued", 0), "verification_count": counts.get("verification_required", 0), "mapping_count": counts.get("needs_mapping", 0), "failed_count": counts.get("failed", 0)})


@app.get("/api/tasks/<task_state>")
@require_dashboard_auth
def tasks_by_state(task_state: str):
    allowed = {"verification-required": "verification_required", "needs-mapping": "needs_mapping", "failed": "failed", "queued": "queued", "purchased": "purchased"}
    state = allowed.get(task_state)
    if not state:
        return jsonify({"error": "Unknown task state"}), 404
    conn = get_db()
    rows = [dict(r) for r in conn.execute("""SELECT t.*,o.shopify_order_number,o.customer_name,li.title product_name,li.sku FROM tasks t JOIN orders o ON o.id=t.order_id LEFT JOIN line_items li ON li.id=t.line_item_id WHERE t.state=? ORDER BY t.updated_at DESC""", (state,))]
    conn.close()
    return jsonify({"tasks": rows})


@app.get("/api/tasks/verification-required")
@require_dashboard_auth
def verification_tasks():
    return tasks_by_state("verification-required")


@app.get("/api/tasks/needs-mapping")
@require_dashboard_auth
def mapping_tasks():
    return tasks_by_state("needs-mapping")


@app.get("/api/catalog")
@require_dashboard_auth
def catalog():
    conn = get_db()
    rows = [dict(r) for r in conn.execute("SELECT * FROM products ORDER BY product_name")]
    conn.close()
    return jsonify({"products": rows})


@app.post("/api/catalog/import")
@require_dashboard_auth
def import_catalog():
    products = (request.get_json(silent=True) or {}).get("products") or []
    if not products:
        return jsonify({"error": "No products provided"}), 400
    conn = get_db()
    imported = 0
    for p in products:
        if not p.get("sku") or not p.get("asin") or not p.get("amazon_url"):
            continue
        conn.execute("""INSERT INTO products(sku,asin,amazon_url,product_name,buy_price,sell_price,category,is_active,stock_status,notes) VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(sku) DO UPDATE SET asin=excluded.asin,amazon_url=excluded.amazon_url,product_name=excluded.product_name,buy_price=excluded.buy_price,sell_price=excluded.sell_price,category=excluded.category,is_active=excluded.is_active,stock_status=excluded.stock_status,notes=excluded.notes""", (p["sku"], p["asin"], p["amazon_url"], p.get("product_name"), p.get("buy_price"), p.get("sell_price"), p.get("category"), 1 if p.get("is_active", True) else 0, p.get("stock_status", "in_stock"), p.get("notes", "")))
        imported += 1
    conn.commit()
    conn.close()
    return jsonify({"status": "imported", "count": imported})


@app.route("/webhooks/shopify/orders-create", methods=["POST"])
@app.route("/webhooks/shopify/orders-updated", methods=["POST"])
@app.route("/webhooks/shopify/orders-cancelled", methods=["POST"])
def order_webhook():
    raw = request.get_data()
    if not verify_shopify_webhook(raw, request.headers.get("X-Shopify-Hmac-Sha256", "")):
        return jsonify({"error": "Invalid signature"}), 401
    try:
        order = normalize_rest_order(request.get_json(force=True))
        conn = get_db()
        _, created = upsert_order(conn, order, create_tasks=True)
        conn.commit()
        conn.close()
        return jsonify({"status": "created" if created else "updated"})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/api/queue/next")
@require_worker_auth
def next_task():
    conn = get_db()
    task = conn.execute("""SELECT t.*,o.shopify_order_id,o.shopify_order_number,o.customer_name,o.shipping_address FROM tasks t JOIN orders o ON o.id=t.order_id WHERE t.state='queued' ORDER BY t.created_at LIMIT 1""").fetchone()
    if not task:
        conn.close()
        return jsonify({"task": None})
    conn.execute("UPDATE tasks SET state='processing_opened_url',updated_at=?,last_action='Worker pulled task' WHERE id=?", (utcnow(), task["id"]))
    conn.commit()
    result = dict(task)
    conn.close()
    return jsonify({"task": result})


@app.post("/api/queue/<int:task_id>/update")
@require_worker_auth
def update_task(task_id: int):
    body = request.get_json(silent=True) or {}
    state = str(body.get("state") or "").strip()
    if not state:
        return jsonify({"error": "state required"}), 400
    conn = get_db()
    conn.execute("UPDATE tasks SET state=?,error_message=?,amazon_order_id=?,last_action=?,updated_at=? WHERE id=?", (state, body.get("error_message"), body.get("amazon_order_id"), body.get("last_action"), utcnow(), task_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "updated"})


@app.post("/api/worker/heartbeat")
@require_worker_auth
def heartbeat():
    body = request.get_json(silent=True) or {}
    conn = get_db()
    conn.execute("UPDATE worker_status SET is_online=1,last_heartbeat_at=?,last_action=?,last_error=? WHERE id=1", (utcnow(), body.get("action", "Heartbeat"), body.get("error")))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.get("/shopify/install")
def shopify_install():
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        missing = [name for name, value in {"SHOPIFY_CLIENT_ID": SHOPIFY_CLIENT_ID, "SHOPIFY_CLIENT_SECRET": SHOPIFY_CLIENT_SECRET}.items() if not value]
        return jsonify({"error": "Shopify OAuth is not configured", "missing": missing}), 503
    shop = str(request.args.get("shop") or SHOPIFY_STORE_DOMAIN or "").strip().lower()
    if not is_valid_shop_domain(shop):
        return jsonify({"error": "Invalid Shopify shop domain"}), 400
    if request.args.get("hmac") and not verify_shopify_oauth_hmac(request.args):
        return jsonify({"error": "Invalid Shopify installation HMAC"}), 401
    state = secrets.token_urlsafe(32)
    params = {"client_id": SHOPIFY_CLIENT_ID, "scope": SHOPIFY_SCOPES, "redirect_uri": SHOPIFY_REDIRECT_URI, "state": state}
    response = make_response(redirect(f"https://{shop}/admin/oauth/authorize?{urlencode(params)}", code=302))
    cookie_options = {"max_age": 600, "secure": not is_local_request(), "httponly": True, "samesite": "Lax"}
    response.set_cookie("shopify_oauth_state", state, **cookie_options)
    response.set_cookie("shopify_oauth_shop", shop, **cookie_options)
    return response


@app.get("/shopify/callback")
def shopify_callback():
    required = ["code", "shop", "state", "hmac"]
    missing = [name for name in required if not request.args.get(name)]
    if missing:
        return jsonify({"error": "Missing OAuth callback parameters", "missing": missing}), 400
    shop = str(request.args.get("shop") or "").strip().lower()
    state = str(request.args.get("state") or "")
    if not is_valid_shop_domain(shop):
        return jsonify({"error": "Invalid Shopify shop domain"}), 400
    expected_state = request.cookies.get("shopify_oauth_state", "")
    expected_shop = request.cookies.get("shopify_oauth_shop", "")
    if not expected_state or not secrets.compare_digest(state, expected_state):
        return jsonify({"error": "OAuth state validation failed"}), 401
    if expected_shop and not secrets.compare_digest(shop, expected_shop):
        return jsonify({"error": "OAuth shop validation failed"}), 401
    if not verify_shopify_oauth_hmac(request.args):
        return jsonify({"error": "OAuth HMAC validation failed"}), 401
    try:
        token_response = requests.post(f"https://{shop}/admin/oauth/access_token", json={"client_id": SHOPIFY_CLIENT_ID, "client_secret": SHOPIFY_CLIENT_SECRET, "code": request.args["code"]}, timeout=30)
        token_data = token_response.json()
    except requests.RequestException as exc:
        return jsonify({"error": "Unable to contact Shopify token endpoint", "detail": str(exc)}), 502
    except ValueError:
        return jsonify({"error": "Shopify token endpoint returned invalid JSON"}), 502
    if not token_response.ok:
        return jsonify({"error": "Shopify token exchange failed", "detail": token_data}), 502
    access_token = str(token_data.get("access_token") or "")
    if not access_token:
        return jsonify({"error": "Shopify did not return an access token"}), 502
    save_shopify_connection(shop, access_token, str(token_data.get("scope") or ""))
    response = make_response("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Shopify connected</title></head><body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#07111f;color:#fff;font-family:Arial,sans-serif"><main style="max-width:560px;padding:32px;text-align:center"><h1>Shopify connected successfully</h1><p>FulfillmentPro securely stored the offline Admin API access token for this store.</p><p>You can now return to the dashboard and run Shopify synchronization.</p><a href="/" style="display:inline-block;margin-top:16px;padding:12px 20px;background:#1378ff;color:#fff;text-decoration:none;border-radius:8px">Open FulfillmentPro</a></main></body></html>""", 200)
    response.delete_cookie("shopify_oauth_state")
    response.delete_cookie("shopify_oauth_shop")
    return response


@app.get("/api/shopify/connection")
@require_dashboard_auth
def shopify_connection_status():
    connection = get_shopify_connection(SHOPIFY_STORE_DOMAIN)
    return jsonify({"connected": bool(connection), "shop_domain": SHOPIFY_STORE_DOMAIN, "granted_scopes": connection.get("granted_scopes") if connection else "", "installed_at": connection.get("installed_at") if connection else None})


@app.get("/")
def index():
    return send_from_directory("static", "index.html")


@app.get("/<path:path>")
def static_file(path: str):
    return send_from_directory("static", path)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)


@app.route("/api/shopify/status", methods=["GET"])
def shopify_status():
    """
    Dashboard-friendly Shopify connection status.
    """
    try:
        token = get_shopify_access_token(SHOPIFY_STORE_DOMAIN)

        return jsonify({
            "connected": bool(token),
            "shop": SHOPIFY_STORE_DOMAIN,
        })

    except Exception as e:
        return jsonify({
            "connected": False,
            "shop": SHOPIFY_STORE_DOMAIN,
            "error": str(e),
        }), 500
