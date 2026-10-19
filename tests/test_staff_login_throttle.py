from fastapi.testclient import TestClient
from app import main,staff_auth


def test_staff_login_rate_limit_and_reset(tmp_path,monkeypatch):
    monkeypatch.setattr(main,"DB",str(tmp_path/"staff-rate-limit.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY","test-key")
    staff_auth._attempts.clear()
    main.setup()
    client=TestClient(main.app)
    headers={"X-Admin-Key":"test-key"}
    payload={"username":"staff_limit_test","display_name":"Staff Limit","password":"strong-password-123","school_id":1,"role":"staff"}
    assert client.post("/api/staff-auth/accounts",json=payload,headers=headers).status_code==201
    wrong={"username":"staff_limit_test","password":"incorrect"}
    for _ in range(5):
        assert client.post("/api/staff-auth/login",json=wrong).status_code==401
    blocked=client.post("/api/staff-auth/login",json={"username":"staff_limit_test","password":"strong-password-123"})
    assert blocked.status_code==429
    assert blocked.headers["retry-after"]=="300"
    staff_auth._attempts.clear()
    assert client.post("/api/staff-auth/login",json={"username":"staff_limit_test","password":"strong-password-123"}).status_code==200
    assert not staff_auth._attempts
