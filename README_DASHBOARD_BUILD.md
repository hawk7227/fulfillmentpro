# FulfillmentPro Shopify Dashboard Build

## Delivered behavior

- Imports existing Shopify orders through Admin GraphQL.
- Continues receiving new and updated orders through verified Shopify webhooks.
- Stores Shopify financial, fulfillment, shipping, tracking, customer, product and line-item data in the existing SQLite database.
- Creates automation tasks in the existing queue only when line items are first encountered.
- Preserves worker endpoints and task state updates.
- Protects order, customer, task and dashboard APIs with an owner bearer token.
- Shows live totals, paid, fulfilled, delivered, refunds, revenue, queue, mappings, verification, failures, worker state, recent orders and top products.
- Supports search, status filters, order details, manual Shopify synchronization, automatic refresh and mobile navigation.

## Required Railway variables

```env
DATABASE_PATH=/data/fulfillment.db
WORKER_AUTH_TOKEN=<existing worker token>
DASHBOARD_AUTH_TOKEN=<new owner-only token>
SHOPIFY_WEBHOOK_SECRET=<Shopify webhook signing secret>
SHOPIFY_STORE_DOMAIN=br1xzv-gd.myshopify.com
SHOPIFY_ADMIN_ACCESS_TOKEN=<Shopify Admin API access token>
SHOPIFY_API_VERSION=2025-10
```

Attach a Railway persistent volume and mount it at `/data` so SQLite survives redeployments.

## Shopify scopes

The Admin API token needs at least `read_orders`. Product imagery and broader product data may also require `read_products`. Older-than-60-day order history requires the applicable Shopify approval and `read_all_orders` access.

## Webhook URLs

Configure these Shopify webhooks using the same signing secret:

- `POST https://fulfillmentpro.up.railway.app/webhooks/shopify/orders-create`
- `POST https://fulfillmentpro.up.railway.app/webhooks/shopify/orders-updated`
- `POST https://fulfillmentpro.up.railway.app/webhooks/shopify/orders-cancelled`

## Verification

```bash
python -m py_compile backend.py
python -m pytest -q
```

The included tests verify authentication, HMAC webhook ingestion, SQLite persistence, Shopify sync wiring and Windows worker queue compatibility.

## Shopify OAuth installation

This package now includes a complete standalone Shopify OAuth flow.

Railway variables:

```env
SHOPIFY_STORE_DOMAIN=br1xzv-gd.myshopify.com
SHOPIFY_CLIENT_ID=<Shopify Client ID>
SHOPIFY_CLIENT_SECRET=<Shopify Client secret>
SHOPIFY_WEBHOOK_SECRET=<same Shopify Client secret>
SHOPIFY_SCOPES=read_orders,read_products,read_customers,read_fulfillments,read_inventory,read_locations
SHOPIFY_REDIRECT_URI=https://fulfillmentpro.up.railway.app/shopify/callback
SHOPIFY_API_VERSION=2025-10
```

In the Shopify app version configuration set:

- App URL: `https://fulfillmentpro.up.railway.app/shopify/install`
- Allowed redirect URL: `https://fulfillmentpro.up.railway.app/shopify/callback`
- Turn off embedded mode for this standalone Flask deployment.

After Railway deploys, open:

`https://fulfillmentpro.up.railway.app/shopify/install?shop=br1xzv-gd.myshopify.com`

The callback stores the offline Admin API token in the persistent SQLite database. The Shopify synchronization code reads this stored token first and uses `SHOPIFY_ADMIN_ACCESS_TOKEN` only as a fallback.
