import requests, uuid
res = requests.post("http://127.0.0.1:8000/api/v1/conversations", json={})
c_id = res.json()["id"]
res = requests.post("http://127.0.0.1:8000/api/v1/runs", json={
    "conversation_id": c_id, "query": "hi3", "mode": "quick", "source_scope": ["web"], "document_ids": []
}, headers={"Idempotency-Key": str(uuid.uuid4())})
print(res.status_code, res.text)
