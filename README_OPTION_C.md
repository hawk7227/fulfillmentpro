# FulfillmentPro Option C Dashboard

## GitHub push path

Replace this repository file:

`static/index.html`

with:

`static/index.html`

from this package.

Do not replace backend.py for this step.

## What this dashboard uses

- `GET /api/dashboard`
- `POST /api/shopify/sync`
- `GET /api/orders`
- `GET /api/orders/<id>`

The dashboard includes Shopify connection state, Sync Shopify controls,
live order metrics, recent orders, workflow counts, and owner authentication.

## Commit

```bash
git add static/index.html
git commit -m "Deploy Option C Shopify-powered dashboard"
git push
```
