from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "static" / "index.html"
BACKEND = ROOT / "backend.py"


def patch_index() -> bool:
    text = INDEX.read_text(encoding="utf-8")
    original = text

    css_link = '<link rel="stylesheet" href="/css/fulfillment-notifications.css">'
    if css_link not in text:
        text = text.replace(
            '<link rel="manifest" href="/manifest.json">',
            '<link rel="manifest" href="/manifest.json">' + css_link,
            1,
        )

    script_tag = '<script src="/js/fulfillment-notifications.js"></script>'
    if script_tag not in text:
        marker = '<script>\n(async function removeLegacyDashboardCache()'
        if marker not in text:
            raise RuntimeError("Could not locate dashboard cache-cleanup script marker")
        text = text.replace(marker, script_tag + '\n' + marker, 1)

    old_function = """function showNewOrderPopup(order){
  const number=order.shopify_order_number||order.id;
  $('newOrderPopupTitle').textContent='#'+number+' · '+(order.customer_name||'Customer');
  $('newOrderPopupDetails').textContent=(order.item_count||0)+' item'+((order.item_count||0)===1?'':'s')+' · '+money(order.current_total_price||order.total_price,order.currency);
  $('newOrderPopup')?.classList.add('show');
  if('Notification' in window&&Notification.permission==='granted'){try{new Notification('New Shopify order #'+number,{body:(order.customer_name||'Customer')+' · '+money(order.current_total_price||order.total_price,order.currency),tag:'fulfillmentpro-order-'+order.id})}catch{}}
  liveState.popupTimer=setTimeout(hideNewOrderPopup,12000);
}"""
    new_function = """function showNewOrderPopup(order){
  if(window.FulfillmentNotifications){
    window.FulfillmentNotifications.notify(order);
    return;
  }
  const number=order.shopify_order_number||order.id;
  $('newOrderPopupTitle').textContent='#'+number+' · '+(order.customer_name||'Customer');
  $('newOrderPopupDetails').textContent=(order.item_count||0)+' item'+((order.item_count||0)===1?'':'s')+' · '+money(order.current_total_price||order.total_price,order.currency);
  $('newOrderPopup')?.classList.add('show');
  if('Notification' in window&&Notification.permission==='granted'){try{new Notification('New Shopify order #'+number,{body:(order.customer_name||'Customer')+' · '+money(order.current_total_price||order.total_price,order.currency),tag:'fulfillmentpro-order-'+order.id})}catch{}}
  liveState.popupTimer=setTimeout(hideNewOrderPopup,12000);
}"""
    if "window.FulfillmentNotifications.notify(order)" not in text:
        if old_function not in text:
            raise RuntimeError("Could not locate existing showNewOrderPopup implementation")
        text = text.replace(old_function, new_function, 1)

    if text != original:
        INDEX.write_text(text, encoding="utf-8")
        return True
    return False


def patch_backend() -> bool:
    text = BACKEND.read_text(encoding="utf-8")
    original = text

    old = '''def latest_order():
    conn = get_db()
    row = conn.execute("""SELECT id,shopify_order_id,shopify_order_number,customer_name,current_total_price,total_price,currency,item_count,created_at,financial_status,fulfillment_status FROM orders ORDER BY id DESC LIMIT 1""").fetchone()
    conn.close()
    return jsonify({"order": dict(row) if row else None})'''

    new = '''def latest_order():
    conn = get_db()
    row = conn.execute("""SELECT id,shopify_order_id,shopify_order_number,customer_name,current_total_price,total_price,currency,item_count,created_at,financial_status,fulfillment_status,source_name FROM orders ORDER BY id DESC LIMIT 1""").fetchone()
    order = dict(row) if row else None
    if order:
        items = [dict(item) for item in conn.execute(
            """SELECT li.*, p.buy_price, p.sell_price
               FROM line_items li
               LEFT JOIN products p ON UPPER(TRIM(p.sku)) = UPPER(TRIM(li.sku))
               WHERE li.order_id=? ORDER BY li.id LIMIT 4""",
            (order["id"],),
        )]
        order["items"] = items
        order["product_title"] = items[0].get("title") if items else None
        order["image_url"] = items[0].get("image_url") if items else None
        order["estimated_cost"] = sum(
            float(item.get("buy_price") or 0) * int(item.get("quantity") or 1)
            for item in items
        )
        order["estimated_profit"] = (
            float(order.get("current_total_price") or order.get("total_price") or 0)
            - order["estimated_cost"]
            if order["estimated_cost"]
            else None
        )
    conn.close()
    return jsonify({"order": order})'''

    if 'order["estimated_profit"]' not in text:
        if old not in text:
            raise RuntimeError("Could not locate latest_order endpoint")
        text = text.replace(old, new, 1)

    if text != original:
        BACKEND.write_text(text, encoding="utf-8")
        return True
    return False


if __name__ == "__main__":
    changed = [name for name, did_change in (("static/index.html", patch_index()), ("backend.py", patch_backend())) if did_change]
    print("Updated: " + ", ".join(changed) if changed else "Notification integration already applied")
