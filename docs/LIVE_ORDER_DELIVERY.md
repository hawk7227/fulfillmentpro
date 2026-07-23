# Live Shopify order delivery

FulfillmentPro receives new Shopify orders through Admin API webhooks instead of requiring the dashboard Sync Shopify button.

## Required production configuration

- `SHOPIFY_STORE_DOMAIN`
- `SHOPIFY_ADMIN_ACCESS_TOKEN` or an installed OAuth connection
- `SHOPIFY_WEBHOOK_SECRET`
- `SHOPIFY_WEBHOOK_BASE_URL=https://fulfillmentpro.up.railway.app`
- `DASHBOARD_AUTH_TOKEN`

## Automatic registration

At application startup FulfillmentPro verifies these subscriptions and creates any that are missing:

- `ORDERS_CREATE` → `/webhooks/shopify/orders-create`
- `ORDERS_UPDATED` → `/webhooks/shopify/orders-updated`
- `ORDERS_CANCELLED` → `/webhooks/shopify/orders-cancelled`

Status is available from `GET /api/shopify/webhooks/status` using dashboard authentication. A manual repair can be run through `POST /api/shopify/webhooks/ensure-live`.

## Dashboard behavior

The notification client polls persisted notification events every four seconds. On `order_placed` it:

1. shows the existing loud order popup;
2. marks Orders red;
3. dispatches `fulfillmentpro:new-order`;
4. clicks the home dashboard Refresh control so the new row appears without a page refresh.

Desktop navigation to Orders, Queue, Mapping, and Notifications is injected into the home sidebar and as operation cards below the page heading. Mobile navigation remains unchanged.
