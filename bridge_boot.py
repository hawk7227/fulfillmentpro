"""FulfillmentPro production entrypoint with live bridge UI injection."""
from __future__ import annotations

from live_bridge import app
import notification_extension  # noqa: F401,E402
import webhook_autoregistration  # noqa: F401,E402


DASHBOARD_PAGE_LINKS = """
<section class="fp-direct-page-links" aria-label="FulfillmentPro pages">
  <a href="/orders.html"><span>🛒</span><div><b>Orders</b><small>View all Shopify orders</small></div></a>
  <a href="/queue.html"><span>📦</span><div><b>Fulfillment Queue</b><small>See active and waiting work</small></div></a>
  <a href="/mapping.html"><span>🔗</span><div><b>Product Mapping</b><small>Fix unmapped order items</small></div></a>
  <a href="/notifications.html"><span>🔔</span><div><b>Notifications</b><small>Open fulfillment alerts</small></div></a>
</section>
"""

DASHBOARD_PAGE_LINK_STYLES = """
<style id="fp-direct-page-link-styles">
.fp-direct-page-links{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 16px}
.fp-direct-page-links a{display:flex;align-items:center;gap:12px;min-height:74px;padding:14px 16px;border:1px solid #173d63;border-radius:14px;background:linear-gradient(145deg,#0a2037,#071522);color:#f5f8ff;text-decoration:none;box-shadow:0 4px 14px rgba(0,0,0,.2);transition:transform .15s ease,border-color .15s ease}
.fp-direct-page-links a:hover{transform:translateY(-2px);border-color:#2e8cff}
.fp-direct-page-links span{display:grid;place-items:center;width:40px;height:40px;flex:0 0 40px;border-radius:12px;background:#12345a;font-size:1.1rem}
.fp-direct-page-links b{display:block;font-size:.9rem}.fp-direct-page-links small{display:block;margin-top:4px;color:#91a5bb;font-size:.7rem}
@media(max-width:1050px) and (min-width:768px){.fp-direct-page-links{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:767px){.fp-direct-page-links{display:none!important}}
</style>
"""


@app.after_request
def inject_live_bridge_script(response):
    content_type = response.headers.get("Content-Type", "")
    if (
        response.status_code == 200
        and "text/html" in content_type
        and not response.direct_passthrough
    ):
        body = response.get_data(as_text=True)
        style_marker = '<link rel="stylesheet" href="/css/fulfillment-notifications-live.css">'
        scripts = [
            '<script src="/js/desktop-operations-nav.js"></script>',
            '<script src="/js/live-bridge.js"></script>',
        ]
        if style_marker not in body and "</head>" in body:
            body = body.replace("</head>", f"{style_marker}</head>")
        if "fp-direct-page-link-styles" not in body and "</head>" in body:
            body = body.replace("</head>", f"{DASHBOARD_PAGE_LINK_STYLES}</head>")
        if request_path_is_dashboard() and "fp-direct-page-links" not in body:
            heading = '<div class="heading-row"><div><h1>Welcome back, Marcus! 👋</h1><p>Live Shopify orders and fulfillment operations.</p></div><button id="viewShopify" class="primary">View Shopify</button></div>'
            if heading in body:
                body = body.replace(heading, heading + DASHBOARD_PAGE_LINKS, 1)
        for script_marker in scripts:
            if script_marker not in body and "</body>" in body:
                body = body.replace("</body>", f"{script_marker}</body>")
        response.set_data(body)
        response.headers["Content-Length"] = str(len(response.get_data()))

    return response


def request_path_is_dashboard() -> bool:
    from flask import request

    return request.path in {"/", "/index.html"}
