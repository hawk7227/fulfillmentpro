# FulfillmentPro OAuth Upgrade

This build adds a complete standalone Shopify OAuth authorization-code flow to the improved Shopify dashboard package.

## Added

- `GET /shopify/install`
- `GET /shopify/callback`
- OAuth HMAC and state verification
- Offline Admin API token exchange
- Durable `shopify_connections` SQLite storage
- Stored-token-first Shopify GraphQL authentication
- `GET /api/shopify/connection`
- Dashboard **Connect Shopify** behavior when no token exists
- OAuth tests, bad-state tests, and bad-HMAC tests

## Shopify configuration

- App URL: `https://fulfillmentpro.up.railway.app/shopify/install`
- Redirect URL: `https://fulfillmentpro.up.railway.app/shopify/callback`
- Standalone app: embedded mode off

## Installation URL

`https://fulfillmentpro.up.railway.app/shopify/install?shop=br1xzv-gd.myshopify.com`
