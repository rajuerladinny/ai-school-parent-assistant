from datetime import date
from fastapi.testclient import TestClient
from app import main, policies, conflicts
import pytest

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main,"DB",str(tmp_path/"conflicts.db"))
    monkeypatch.setenv("SCHOOL_ADMIN_KEY","secret")
    monkeypatch.setattr(main,"rebuild_index",lambda: True)
    policies.configure(main.db,main.auth,main.extract_text,main.rebuild_index)
    conflicts.configure(main.db,main.auth,main.rebuild_index)
    main.setup()
    return TestClient(main.app)

def test_overlapping_faq_blocks_approval_until_deactivated(client):
    headers={"X-Admin-Key":"secret"}
    response=client.post("/api/policies",headers=headers,
        data={"policy_key":"fees","title":"Fees","effective_date":date.today().isoformat()},
        files={"file":("fees.txt",b"Fees are due on June 20, according to the approved school policy.")})
    assert response.status_code==201
    policy_id=response.json()["id"]
    review=f"/api/policies/{policy_id}/review"
    denied=client.post(review,headers=headers,json={"approve":True})
    assert denied.status_code==409
    pending=client.get("/api/conflicts",headers=headers).json()
    assert len(pending)==1 and pending[0]["status"]=="open"
    legacy_id=pending[0]["legacy_id"]
    assert client.post(f"/api/conflicts/legacy/faq/{legacy_id}/deactivate",headers=headers).status_code==200
    assert client.post(review,headers=headers,json={"approve":True}).status_code==200
    with main.db() as c:
        items=main.records_for_index()
        assert not any(x["id"]==f"faq-{legacy_id}" for x in items)
        assert any(x["id"]==f"policy-{policy_id}" for x in items)

def test_conflict_management_requires_admin_auth(client):
    assert client.get("/api/conflicts").status_code==401
    assert client.post("/api/conflicts/legacy/faq/1/deactivate").status_code==401
    assert client.post("/api/conflicts/scan/1").status_code==401

def test_unrelated_policy_can_be_approved(client):
    headers={"X-Admin-Key":"secret"}
    r=client.post("/api/policies",headers=headers,
        data={"policy_key":"library","title":"Library","effective_date":date.today().isoformat()},
        files={"file":("library.txt",b"The library is open Monday through Friday from 9 AM until 2 PM.")})
    assert r.status_code==201
    assert client.post(f"/api/policies/{r.json()['id']}/review",headers=headers,json={"approve":True}).status_code==200
