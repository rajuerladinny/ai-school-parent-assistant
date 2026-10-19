from fastapi.testclient import TestClient
from app import main, observability


def test_request_ids_are_server_generated_and_sensitive_data_not_in_metrics():
    client=TestClient(main.app)
    before=observability.snapshot()
    response=client.get("/docs",headers={
        "X-Request-ID":"attacker-supplied-id",
        "Authorization":"Bearer private-token",
    })
    assert response.headers["X-Request-ID"]!="attacker-supplied-id"
    assert len(response.headers["X-Request-ID"])==32
    after=observability.snapshot()
    assert after.get("GET:2xx",0)+after.get("GET:4xx",0)>=before.get("GET:2xx",0)+before.get("GET:4xx",0)+1
    assert "private-token" not in str(after)
    assert "/docs" not in str(after)
