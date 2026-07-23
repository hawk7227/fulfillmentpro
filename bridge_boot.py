"""FulfillmentPro production entrypoint with live bridge UI injection."""
from __future__ import annotations

from live_bridge import app
import notification_extension  # noqa: F401,E402


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
        script_marker = '<script src="/js/live-bridge.js"></script>'
        if style_marker not in body and "</head>" in body:
            body = body.replace("</head>", f"{style_marker}</head>")
        if script_marker not in body and "</body>" in body:
            body = body.replace("</body>", f"{script_marker}</body>")
        response.set_data(body)
        response.headers["Content-Length"] = str(len(response.get_data()))

    return response
