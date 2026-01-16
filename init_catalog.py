"""Import products.json into database"""
import json
import requests
import os

BACKEND_URL = os.getenv('BACKEND_URL', 'http://localhost:5000')

with open('products.json', 'r') as f:
    data = json.load(f)

response = requests.post(
    f'{BACKEND_URL}/api/catalog/import',
    json=data
)

print(f"Import status: {response.status_code}")
print(response.json())
