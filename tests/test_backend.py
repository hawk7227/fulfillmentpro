import base64, hashlib, hmac, importlib, json, os

def load_app(tmp):
    os.environ['DATABASE_PATH']=str(tmp/'test.db');os.environ['WORKER_AUTH_TOKEN']='worker-secret';os.environ['DASHBOARD_AUTH_TOKEN']='owner-secret';os.environ['SHOPIFY_WEBHOOK_SECRET']='webhook-secret';os.environ['SHOPIFY_CLIENT_ID']='client-id';os.environ['SHOPIFY_CLIENT_SECRET']='client-secret';os.environ['SHOPIFY_STORE_DOMAIN']='shop.myshopify.com';os.environ['SHOPIFY_REDIRECT_URI']='http://localhost/shopify/callback';os.environ.pop('SHOPIFY_ADMIN_ACCESS_TOKEN',None)
    import backend;importlib.reload(backend);return backend

def auth():return {'Authorization':'Bearer owner-secret'}

def test_health_and_auth(tmp_path):
    app=load_app(tmp_path).app.test_client();assert app.get('/health').status_code==200;assert app.get('/api/dashboard').status_code==401;assert app.post('/api/auth/check',headers=auth()).status_code==200

def test_webhook_persists_order(tmp_path):
    mod=load_app(tmp_path);app=mod.app.test_client();payload={'id':123,'order_number':1407,'email':'buyer@example.com','total_price':'33.16','current_total_price':'33.16','currency':'USD','financial_status':'paid','fulfillment_status':None,'created_at':'2026-07-15T01:00:00Z','updated_at':'2026-07-15T01:00:00Z','shipping_address':{'first_name':'Marcus','last_name':'Hawkins','city':'Tempe','province_code':'AZ'},'line_items':[{'id':9,'title':'Test Product','sku':'B000TEST','quantity':1,'price':'33.16'}]};raw=json.dumps(payload,separators=(',',':')).encode();sig=base64.b64encode(hmac.new(b'webhook-secret',raw,hashlib.sha256).digest()).decode();r=app.post('/webhooks/shopify/orders-create',data=raw,headers={'Content-Type':'application/json','X-Shopify-Hmac-Sha256':sig});assert r.status_code==200;d=app.get('/api/dashboard',headers=auth()).get_json();assert d['total_orders']==1 and d['revenue']==33.16 and d['needs_mapping']==1

def test_worker_queue_contract(tmp_path):
    mod=load_app(tmp_path);app=mod.app.test_client();conn=mod.get_db();conn.execute("INSERT INTO products(sku,asin,amazon_url,product_name,is_active) VALUES('X','X','https://example.com/p','P',1)");order={'shopify_order_id':'1','shopify_order_number':'1','customer_name':'Test','customer_email':'x','shipping_address':'{}','total_price':10,'subtotal_price':10,'current_total_price':10,'refunds_total':0,'currency':'USD','created_at':mod.utcnow(),'updated_at':mod.utcnow(),'shopify_updated_at':mod.utcnow(),'processed_at':None,'cancelled_at':None,'closed_at':None,'financial_status':'PAID','fulfillment_status':'UNFULFILLED','delivery_status':None,'source_name':'web','shipping_method':'Shipping','tracking_company':None,'tracking_number':None,'tracking_url':None,'tags':'[]','item_count':1,'synced_at':mod.utcnow(),'line_items':[{'id':'li1','title':'P','sku':'X','quantity':1,'price':10}]};mod.upsert_order(conn,order,True);conn.commit();conn.close();assert app.get('/api/queue/next',headers={'Authorization':'Bearer worker-secret'}).get_json()['task'] is not None


def test_shopify_sync_graphql_wires_to_database(tmp_path, monkeypatch):
    mod=load_app(tmp_path)
    os.environ['SHOPIFY_STORE_DOMAIN']='shop.myshopify.com'
    os.environ['SHOPIFY_ADMIN_ACCESS_TOKEN']='token'
    mod.SHOPIFY_STORE_DOMAIN='shop.myshopify.com';mod.SHOPIFY_ADMIN_ACCESS_TOKEN='token'
    node={'id':'gid://shopify/Order/5','legacyResourceId':'5','name':'#1408','createdAt':'2026-07-15T02:00:00Z','updatedAt':'2026-07-15T02:00:00Z','processedAt':'2026-07-15T02:00:00Z','cancelledAt':None,'closedAt':None,'email':'x@example.com','displayFinancialStatus':'PAID','displayFulfillmentStatus':'UNFULFILLED','sourceName':'web','tags':[],'currentTotalPriceSet':{'shopMoney':{'amount':'12.00','currencyCode':'USD'}},'currentSubtotalPriceSet':{'shopMoney':{'amount':'12.00','currencyCode':'USD'}},'totalRefundedSet':{'shopMoney':{'amount':'0','currencyCode':'USD'}},'customer':{'displayName':'Buyer'},'shippingAddress':{'firstName':'Buyer','lastName':'One'},'shippingLine':{'title':'Shipping'},'lineItems':{'nodes':[]},'fulfillments':[]}
    monkeypatch.setattr(mod,'shopify_graphql',lambda q,v:{'orders':{'pageInfo':{'hasNextPage':False,'endCursor':None},'nodes':[node]}})
    result=mod.sync_shopify_orders(max_pages=1)
    assert result['imported']==1
    app=mod.app.test_client();assert app.get('/api/dashboard',headers=auth()).get_json()['total_orders']==1


def oauth_hmac(params, secret='client-secret'):
    message='&'.join(f"{key}={params[key]}" for key in sorted(params))
    return hmac.new(secret.encode(),message.encode(),hashlib.sha256).hexdigest()

def test_shopify_oauth_install_and_callback_store_token(tmp_path, monkeypatch):
    from urllib.parse import parse_qs,urlparse
    mod=load_app(tmp_path);app=mod.app.test_client()
    install=app.get('/shopify/install?shop=shop.myshopify.com')
    assert install.status_code==302
    query=parse_qs(urlparse(install.headers['Location']).query)
    assert query['client_id']==['client-id']
    assert query['scope'][0].startswith('read_orders')
    state=query['state'][0]
    class FakeResponse:
        ok=True
        def json(self): return {'access_token':'shpat_test_token','scope':'read_orders,read_products'}
    monkeypatch.setattr(mod.requests,'post',lambda *args,**kwargs:FakeResponse())
    params={'code':'temporary-code','shop':'shop.myshopify.com','state':state,'timestamp':'123456'}
    params['hmac']=oauth_hmac(params)
    callback=app.get('/shopify/callback?'+__import__('urllib.parse').parse.urlencode(params))
    assert callback.status_code==200
    connection=mod.get_shopify_connection('shop.myshopify.com')
    assert connection['access_token']=='shpat_test_token'
    assert mod.get_shopify_access_token('shop.myshopify.com')=='shpat_test_token'

def test_shopify_callback_rejects_bad_state_and_hmac(tmp_path):
    from urllib.parse import parse_qs,urlparse,urlencode
    mod=load_app(tmp_path);app=mod.app.test_client()
    install=app.get('/shopify/install?shop=shop.myshopify.com')
    state=parse_qs(urlparse(install.headers['Location']).query)['state'][0]
    params={'code':'c','shop':'shop.myshopify.com','state':'wrong','timestamp':'1'}
    params['hmac']=oauth_hmac(params)
    assert app.get('/shopify/callback?'+urlencode(params)).status_code==401
    params['state']=state;params['hmac']='bad'
    assert app.get('/shopify/callback?'+urlencode(params)).status_code==401
