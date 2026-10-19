from app.observability import alert_candidates


def test_alert_candidates_thresholds():
    assert alert_candidates({}) == []
    assert alert_candidates({"auth:parent:throttled": 9,
                             "auth:staff:unavailable": 0}) == []
    assert alert_candidates({"auth:parent:throttled": 10,
                             "auth:staff:unavailable": 1}) == [
        {"metric": "auth:parent:throttled", "count": 10, "threshold": 10},
        {"metric": "auth:staff:unavailable", "count": 1, "threshold": 1},
    ]


def test_alert_candidates_ignore_unrecognized_metrics():
    assert alert_candidates({"auth:parent:allowed": 100000,
                             "GET:5xx": 20}) == []
