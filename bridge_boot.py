"""FulfillmentPro production entrypoint with live bridge UI injection."""
from __future__ import annotations

from live_bridge import app


@app.after_request
def inject_live_bridge_script(response):
    content_type = response.headers.get("Content-Type", "")
    if (
        response.status_code == 200
        and "text/html" in content_type
        and not response.direct_passthrough
    ):
        body = response.get_data(as_text=True)
        marker = '<script src="/js/live-bridge.js"></script>'
        if marker not in body and "</body>" in body:
            body = body.replace("</body>", f"{marker}</body>")
            response.set_data(body)
            response.headers["Content-Length"] = str(len(response.get_data()))

    return response
