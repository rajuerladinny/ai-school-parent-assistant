import json
import logging
import pytest
from app import observability


def test_auth_events_are_bounded_and_identity_free(caplog):
    with caplog.at_level(logging.INFO, logger="school.operations"):
        observability.auth_event("parent", "throttled")
        observability.auth_event("staff", "unavailable")
    payloads = [json.loads(record.message) for record in caplog.records
                if record.name == "school.operations"]
    assert {"event": "auth_rate_limit", "realm": "parent", "outcome": "throttled"} in payloads
    assert {"event": "auth_rate_limit", "realm": "staff", "outcome": "unavailable"} in payloads
    assert all("username" not in payload and "ip" not in payload for payload in payloads)
    assert observability.snapshot()["auth:parent:throttled"] >= 1
    with pytest.raises(ValueError):
        observability.auth_event("parent", "alice@example.test")
