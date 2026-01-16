"""
FulfillmentPro Backend - Production Ready
Complete implementation with all requirements
"""
import os
import hmac
import hashlib
import json
import sqlite3
import smtplib
from datetime import datetime, timedelta
from functools import wraps
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

# Optional Firebase for push notifications
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    print("⚠️ Firebase not available - push notifications disabled")

app = Flask(__name__, static_folder='static')
CORS(app)

# ==================== CONFIG ====================
SHOPIFY_WEBHOOK_SECRET = os.getenv('SHOPIFY_WEBHOOK_SECRET', '')
WORKER_AUTH_TOKEN = os.getenv('WORKER_AUTH_TOKEN', 'change-me-in-production')
FIREBASE_CREDENTIALS_JSON = os.getenv('FIREBASE_CREDENTIALS_JSON', '')
DATABASE_PATH = os.getenv('DATABASE_PATH', 'fulfillment.db')

# Email configuration for fallback notifications
EMAIL_ENABLED = os.getenv('EMAIL_ENABLED', 'false').lower() == 'true'
EMAIL_SENDER = os.getenv('EMAIL_SENDER', 'storeorders207@gmail.com')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
EMAIL_RECEIVER = os.getenv('EMAIL_RECEIVER', 'storeorders207@gmail.com')
SMTP_SERVER = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))

WORKER_OFFLINE_THRESHOLD = int(os.getenv('WORKER_OFFLINE_THRESHOLD', '120'))  # seconds

# Initialize Firebase if credentials provided
if FIREBASE_AVAILABLE and FIREBASE_CREDENTIALS_JSON:
    try:
        cred = credentials.Certificate(json.loads(FIREBASE_CREDENTIALS_JSON))
        firebase_admin.initialize_app(cred)
        print("✅ Firebase initialized")
    except Exception as e:
        print(f"⚠️ Firebase init failed: {e}")
        FIREBASE_AVAILABLE = False

# ==================== DATABASE ====================
def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        shopify_order_id TEXT UNIQUE NOT NULL,
        shopify_order_number TEXT,
        customer_name TEXT,
        customer_email TEXT,
        shipping_address TEXT,
        total_price REAL,
        created_at TEXT,
        updated_at TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS line_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER,
        shopify_line_item_id TEXT,
        title TEXT,
        variant_title TEXT,
        sku TEXT,
        quantity INTEGER,
        price REAL,
        FOREIGN KEY (order_id) REFERENCES orders(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS tasks (
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
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (line_item_id) REFERENCES line_items(id)
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS worker_status (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        is_online INTEGER DEFAULT 0,
        last_heartbeat_at TEXT,
        last_error TEXT,
        last_action TEXT,
        last_offline_notification_at TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS push_tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        device_label TEXT,
        created_at TEXT
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sku TEXT UNIQUE NOT NULL,
        asin TEXT NOT NULL,
        amazon_url TEXT NOT NULL,
        product_name TEXT,
        buy_price REAL,
        sell_price REAL,
        category TEXT,
        is_active INTEGER DEFAULT 1,
        stock_status TEXT,
        notes TEXT
    )''')
    
    c.execute('INSERT OR IGNORE INTO worker_status (id, is_online) VALUES (1, 0)')
    conn.commit()
    conn.close()
    print("✅ Database initialized")

init_db()

def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def load_products():
    """Load active products into memory for fast lookup"""
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT * FROM products WHERE is_active = 1')
    products = {row['sku']: dict(row) for row in c.fetchall()}
    conn.close()
    return products

# ==================== AUTH ====================
def verify_shopify_webhook(data, hmac_header):
    """Verify Shopify webhook HMAC signature"""
    if not SHOPIFY_WEBHOOK_SECRET:
        print("⚠️ SHOPIFY_WEBHOOK_SECRET not set - skipping verification")
        return True  # Allow in development
    
    import base64
    digest = hmac.new(
        SHOPIFY_WEBHOOK_SECRET.encode('utf-8'),
        data,
        hashlib.sha256
    ).digest()
    computed_hmac = base64.b64encode(digest)
    return hmac.compare_digest(computed_hmac, hmac_header.encode('utf-8'))

def require_worker_auth(f):
    """Decorator to require worker authentication"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token or token != f'Bearer {WORKER_AUTH_TOKEN}':
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# ==================== NOTIFICATIONS ====================
def send_email_notification(subject, body):
    """Send email notification as fallback"""
    if not EMAIL_ENABLED or not EMAIL_PASSWORD:
        return False
    
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        
        print(f"✅ Email sent: {subject}")
        return True
    except Exception as e:
        print(f"❌ Email error: {e}")
        return False

def send_push_notification(title, body, data=None):
    """Send push notification via Firebase"""
    if not FIREBASE_AVAILABLE:
        print(f"⚠️ Push (no Firebase): {title} - {body}")
        return False
    
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT token FROM push_tokens')
    tokens = [row['token'] for row in c.fetchall()]
    conn.close()
    
    if not tokens:
        print("⚠️ No push tokens registered")
        return False
    
    try:
        message = messaging.MulticastMessage(
            notification=messaging.Notification(title=title, body=body),
            data=data or {},
            tokens=tokens
        )
        response = messaging.send_multicast(message)
        print(f"✅ Push sent to {response.success_count}/{len(tokens)} devices")
        return True
    except Exception as e:
        print(f"❌ Push error: {e}")
        return False

def send_notification(title, body, email_body=None, data=None):
    """Send notification via push and email (fallback)"""
    push_sent = send_push_notification(title, body, data)
    
    # Send email as fallback or always (based on config)
    if EMAIL_ENABLED:
        send_email_notification(title, email_body or body)
    
    return push_sent

# ==================== WORKER MONITORING ====================
def check_worker_status():
    """Check if worker is online and send notification if went offline"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT * FROM worker_status WHERE id = 1')
    worker = dict(c.fetchone())
    
    is_online = False
    if worker['last_heartbeat_at']:
        last_hb = datetime.fromisoformat(worker['last_heartbeat_at'])
        is_online = (datetime.utcnow() - last_hb).total_seconds() < WORKER_OFFLINE_THRESHOLD
    
    # Check if we need to send offline notification
    if not is_online and worker['is_online']:
        # Worker just went offline
        last_notif = worker.get('last_offline_notification_at')
        should_notify = True
        
        if last_notif:
            last_notif_time = datetime.fromisoformat(last_notif)
            # Only notify once per hour
            if (datetime.utcnow() - last_notif_time).total_seconds() < 3600:
                should_notify = False
        
        if should_notify:
            send_notification(
                '🔴 Worker Offline',
                'Automation worker is not responding. Tasks are paused.',
                f'Worker last heartbeat: {worker["last_heartbeat_at"]}\n\nPlease check the Windows worker service.',
                {'type': 'worker_offline'}
            )
            
            c.execute('''UPDATE worker_status 
                         SET last_offline_notification_at = ?
                         WHERE id = 1''',
                      (datetime.utcnow().isoformat(),))
            conn.commit()
    
    # Update online status
    if worker['is_online'] != is_online:
        c.execute('UPDATE worker_status SET is_online = ? WHERE id = 1', (1 if is_online else 0,))
        conn.commit()
    
    conn.close()
    return is_online

# ==================== API ENDPOINTS ====================

@app.route('/health', methods=['GET'])
def health():
    """Health check for Railway"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()}), 200

@app.route('/api/status', methods=['GET'])
def get_status():
    """Get system status for dashboard"""
    check_worker_status()  # Update worker status
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT * FROM worker_status WHERE id = 1')
    worker = dict(c.fetchone())
    
    is_online = False
    if worker['last_heartbeat_at']:
        last_hb = datetime.fromisoformat(worker['last_heartbeat_at'])
        is_online = (datetime.utcnow() - last_hb).total_seconds() < WORKER_OFFLINE_THRESHOLD
    
    c.execute('SELECT COUNT(*) as count FROM tasks WHERE state = "queued"')
    queue_size = c.fetchone()['count']
    
    c.execute('SELECT COUNT(*) as count FROM tasks WHERE state = "verification_required"')
    verification_count = c.fetchone()['count']
    
    conn.close()
    
    return jsonify({
        'worker_online': is_online,
        'last_heartbeat_at': worker['last_heartbeat_at'],
        'last_error': worker['last_error'],
        'last_action': worker['last_action'],
        'queue_size': queue_size,
        'verification_count': verification_count
    })

@app.route('/webhooks/shopify/orders-create', methods=['POST'])
def shopify_webhook():
    """Handle Shopify order creation webhook"""
    hmac_header = request.headers.get('X-Shopify-Hmac-Sha256', '')
    
    if not verify_shopify_webhook(request.get_data(), hmac_header):
        print("❌ Invalid webhook signature")
        return jsonify({'error': 'Invalid signature'}), 401
    
    order_data = request.json
    shopify_order_id = str(order_data['id'])
    
    conn = get_db()
    c = conn.cursor()
    
    try:
        # Check for duplicate (idempotency)
        c.execute('SELECT id FROM orders WHERE shopify_order_id = ?', (shopify_order_id,))
        if c.fetchone():
            print(f"⚠️ Order {shopify_order_id} already processed")
            return jsonify({'status': 'already_processed'}), 200
        
        shipping = order_data.get('shipping_address', {})
        
        # Create order record
        c.execute('''INSERT INTO orders 
            (shopify_order_id, shopify_order_number, customer_name, customer_email, 
             shipping_address, total_price, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (shopify_order_id, 
             order_data.get('order_number'),
             f"{shipping.get('first_name', '')} {shipping.get('last_name', '')}".strip(),
             order_data.get('email'), 
             json.dumps(shipping),
             float(order_data.get('total_price', 0)),
             datetime.utcnow().isoformat(), 
             datetime.utcnow().isoformat()))
        
        order_id = c.lastrowid
        products = load_products()
        tasks_created = 0
        needs_mapping = []
        
        # Process line items
        for idx, item in enumerate(order_data.get('line_items', [])):
            shopify_line_item_id = str(item.get('id', ''))
            sku = item.get('sku', '').strip()
            quantity = item.get('quantity', 1)
            title = item.get('title', 'Unknown Product')
            
            # Create line item record
            c.execute('''INSERT INTO line_items 
                (order_id, shopify_line_item_id, title, variant_title, sku, quantity, price)
                VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (order_id, shopify_line_item_id, title,
                 item.get('variant_title'), sku, quantity, float(item.get('price', 0))))
            
            line_item_id = c.lastrowid
            
            # Create unique task key
            unique_key = f"{shopify_order_id}:{shopify_line_item_id or idx}"
            
            # Check for duplicate task (idempotency)
            c.execute('SELECT id FROM tasks WHERE unique_key = ?', (unique_key,))
            if c.fetchone():
                continue
            
            # Validate SKU
            if not sku:
                c.execute('''INSERT INTO tasks 
                    (unique_key, order_id, line_item_id, quantity, state, error_message, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                    (unique_key, order_id, line_item_id, quantity, 'needs_mapping',
                     'No SKU provided', datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
                needs_mapping.append(f"{title} (no SKU)")
                continue
            
            # SKU = ASIN rule
            asin = sku
            product = products.get(asin)
            
            if not product:
                # ASIN not in catalog
                c.execute('''INSERT INTO tasks 
                    (unique_key, order_id, line_item_id, asin, quantity, state, error_message, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (unique_key, order_id, line_item_id, asin, quantity, 'needs_mapping',
                     f'ASIN {asin} not in catalog', datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
                
                needs_mapping.append(f"{title} (ASIN: {asin})")
            else:
                # Product found - create queued task
                c.execute('''INSERT INTO tasks 
                    (unique_key, order_id, line_item_id, asin, amazon_url, quantity, state, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (unique_key, order_id, line_item_id, asin, product['amazon_url'],
                     quantity, 'queued', datetime.utcnow().isoformat(), datetime.utcnow().isoformat()))
                tasks_created += 1
        
        conn.commit()
        
        # Send notifications
        order_number = order_data.get('order_number', shopify_order_id)
        item_count = len(order_data.get('line_items', []))
        
        send_notification(
            '🛍️ New Order Received',
            f"Order #{order_number} - {item_count} item(s)",
            f"Order #{order_number}\nItems: {item_count}\nCustomer: {order_data.get('email', 'N/A')}\nTotal: ${order_data.get('total_price', 0)}",
            {'type': 'new_order', 'order_id': shopify_order_id}
        )
        
        # Send mapping notification if needed
        if needs_mapping:
            send_notification(
                '⚠️ Product Mapping Required',
                f"Order #{order_number} has {len(needs_mapping)} unmapped product(s)",
                f"Order #{order_number}\n\nUnmapped products:\n" + "\n".join(needs_mapping),
                {'type': 'needs_mapping', 'order_id': shopify_order_id}
            )
        
        print(f"✅ Order {order_number} processed: {tasks_created} tasks queued, {len(needs_mapping)} need mapping")
        
        return jsonify({
            'status': 'success', 
            'tasks_created': tasks_created,
            'needs_mapping': len(needs_mapping)
        }), 200
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Webhook error: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/queue/next', methods=['GET'])
@require_worker_auth
def get_next_task():
    """Get next queued task for worker"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT t.*, o.shopify_order_number, o.customer_name, o.shipping_address
                 FROM tasks t
                 JOIN orders o ON t.order_id = o.id
                 WHERE t.state = "queued"
                 ORDER BY t.created_at ASC LIMIT 1''')
    
    task = c.fetchone()
    
    if not task:
        conn.close()
        return jsonify({'task': None}), 200
    
    task_dict = dict(task)
    task_id = task_dict['id']
    
    # Mark as processing
    c.execute('''UPDATE tasks 
                 SET state = "processing_opened_url", updated_at = ?, last_action = ?
                 WHERE id = ?''',
              (datetime.utcnow().isoformat(), 'Worker pulled task', task_id))
    
    conn.commit()
    conn.close()
    
    print(f"📋 Task #{task_id} pulled by worker")
    
    return jsonify({'task': task_dict}), 200

@app.route('/api/queue/<int:task_id>/update', methods=['POST'])
@require_worker_auth
def update_task(task_id):
    """Update task state from worker"""
    data = request.json
    state = data.get('state')
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''UPDATE tasks
                 SET state = ?, error_message = ?, amazon_order_id = ?, 
                     last_action = ?, updated_at = ?
                 WHERE id = ?''',
              (state, 
               data.get('error_message'), 
               data.get('amazon_order_id'),
               data.get('last_action'), 
               datetime.utcnow().isoformat(), 
               task_id))
    
    # Get order info for notifications
    c.execute('''SELECT o.shopify_order_number, t.asin
                 FROM tasks t
                 JOIN orders o ON t.order_id = o.id
                 WHERE t.id = ?''', (task_id,))
    
    task_info = c.fetchone()
    order_number = task_info['shopify_order_number'] if task_info else f"Task #{task_id}"
    
    conn.commit()
    conn.close()
    
    # Send notifications based on state
    if state == 'verification_required':
        send_notification(
            '🔐 Manual Verification Required',
            f'{order_number} needs manual login/OTP',
            f"Order: {order_number}\nTask ID: {task_id}\n\nPlease log in to Amazon manually. The worker will resume automatically after verification.\n\nAmazon Login: https://www.amazon.com/ap/signin",
            {'type': 'verification_required', 'task_id': str(task_id)}
        )
    elif state == 'failed':
        error_msg = data.get('error_message', 'Unknown error')
        send_notification(
            '❌ Task Failed',
            f'{order_number} - {error_msg[:50]}',
            f"Order: {order_number}\nTask ID: {task_id}\n\nError: {error_msg}",
            {'type': 'task_failed', 'task_id': str(task_id)}
        )
    elif state == 'purchased':
        amazon_order_id = data.get('amazon_order_id', 'N/A')
        send_notification(
            '✅ Order Purchased',
            f'{order_number} purchased on Amazon',
            f"Order: {order_number}\nTask ID: {task_id}\nAmazon Order ID: {amazon_order_id}",
            {'type': 'purchased', 'task_id': str(task_id)}
        )
    
    print(f"✅ Task #{task_id} updated to {state}")
    
    return jsonify({'status': 'updated'}), 200

@app.route('/api/worker/heartbeat', methods=['POST'])
@require_worker_auth
def worker_heartbeat():
    """Worker heartbeat endpoint"""
    data = request.json or {}
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''UPDATE worker_status
                 SET is_online = 1, last_heartbeat_at = ?, last_action = ?
                 WHERE id = 1''',
              (datetime.utcnow().isoformat(), data.get('action', 'Heartbeat')))
    
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'ok'}), 200

@app.route('/api/push/subscribe', methods=['POST'])
def subscribe_push():
    """Subscribe device to push notifications"""
    data = request.json
    token = data.get('token')
    
    if not token:
        return jsonify({'error': 'Token required'}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''INSERT OR REPLACE INTO push_tokens (token, device_label, created_at)
                 VALUES (?, ?, ?)''',
              (token, data.get('device_label', 'Unknown'), datetime.utcnow().isoformat()))
    
    conn.commit()
    conn.close()
    
    print(f"✅ Push token registered: {data.get('device_label', 'Unknown')}")
    
    return jsonify({'status': 'subscribed'}), 200

@app.route('/api/orders', methods=['GET'])
def get_orders():
    """Get recent orders with task summary"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT o.*, 
                 COUNT(t.id) as total_tasks,
                 SUM(CASE WHEN t.state = "purchased" THEN 1 ELSE 0 END) as completed_tasks,
                 SUM(CASE WHEN t.state = "verification_required" THEN 1 ELSE 0 END) as verification_tasks,
                 SUM(CASE WHEN t.state = "needs_mapping" THEN 1 ELSE 0 END) as mapping_tasks,
                 SUM(CASE WHEN t.state = "failed" THEN 1 ELSE 0 END) as failed_tasks
                 FROM orders o
                 LEFT JOIN tasks t ON o.id = t.order_id
                 GROUP BY o.id
                 ORDER BY o.created_at DESC LIMIT 100''')
    
    orders = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify({'orders': orders}), 200

@app.route('/api/orders/<int:order_id>', methods=['GET'])
def get_order_detail(order_id):
    """Get detailed order info with line items and tasks"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT * FROM orders WHERE id = ?', (order_id,))
    order_row = c.fetchone()
    
    if not order_row:
        conn.close()
        return jsonify({'error': 'Order not found'}), 404
    
    order = dict(order_row)
    
    # Get line items with task status
    c.execute('''SELECT li.*, t.state, t.amazon_url, t.error_message, t.last_action, t.quantity as task_quantity
                 FROM line_items li
                 LEFT JOIN tasks t ON li.id = t.line_item_id
                 WHERE li.order_id = ?''', (order_id,))
    
    order['items'] = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify({'order': order}), 200

@app.route('/api/tasks/verification-required', methods=['GET'])
def get_verification_tasks():
    """Get all tasks requiring manual verification"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT t.*, o.shopify_order_number, li.title as product_name
                 FROM tasks t
                 JOIN orders o ON t.order_id = o.id
                 LEFT JOIN line_items li ON t.line_item_id = li.id
                 WHERE t.state = "verification_required"
                 ORDER BY t.updated_at DESC''')
    
    tasks = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify({'tasks': tasks}), 200
	
@app.route('/api/tasks/needs-mapping', methods=['GET'])
def get_mapping_tasks():
    """Get all tasks requiring product mapping"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT t.*, o.shopify_order_number, li.title as product_name
                 FROM tasks t
                 JOIN orders o ON t.order_id = o.id
                 LEFT JOIN line_items li ON t.line_item_id = li.id
                 WHERE t.state = "needs_mapping"
                 ORDER BY t.updated_at DESC''')
    
    tasks = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return jsonify({'tasks': tasks}), 200


@app.route('/api/catalog/import', methods=['POST'])
def import_catalog():
    """Import product catalog from JSON"""
    data = request.json
    products = data.get('products', [])
    
    if not products:
        return jsonify({'error': 'No products provided'}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    imported = 0
    for product in products:
        try:
            c.execute('''INSERT OR REPLACE INTO products
                         (sku, asin, amazon_url, product_name, buy_price, sell_price, 
                          category, is_active, stock_status, notes)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                      (product['sku'], 
                       product['asin'], 
                       product['amazon_url'],
                       product.get('product_name'),
                       product.get('buy_price'),
                       product.get('sell_price'), 
                       product.get('category'),
                       1 if product.get('is_active', True) else 0,
                       product.get('stock_status', 'in_stock'),
                       product.get('notes', '')))
            imported += 1
        except Exception as e:
            print(f"⚠️ Failed to import {product.get('sku')}: {e}")
    
    conn.commit()
    conn.close()
    
    print(f"✅ Imported {imported}/{len(products)} products")
    
    return jsonify({'status': 'imported', 'count': imported}), 200

@app.route('/api/catalog', methods=['GET'])
def get_catalog():
    """Get product catalog"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('SELECT * FROM products ORDER BY product_name')
    products = [dict(row) for row in c.fetchall()]
    
    conn.close()
    
    return jsonify({'products': products}), 200

# Serve static files
@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('static', path)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)