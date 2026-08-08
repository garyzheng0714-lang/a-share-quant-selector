from utils import decision_ledger, decision_versions
from utils.pipeline_status import _read_decision, _storage_status


def test_snapshot_retention_is_explicitly_long_term(tmp_path):
    storage = _storage_status(tmp_path)

    assert storage["retention_state"] == "configured"
    assert storage["retention_policy"] == "indefinite"
    assert storage["retention_days"] is None
    assert "不自动删除" in storage["retention_summary"]


def test_pipeline_does_not_present_an_old_code_decision_as_current(monkeypatch):
    monkeypatch.setattr(decision_versions, "strategy_version", lambda: "policy-new")
    monkeypatch.setattr(
        decision_ledger,
        "get_latest_decision",
        lambda _stage: {
            "run_id": "old-run",
            "trade_date": "2026-08-07",
            "strategy_version": "policy-old",
            "data_version": "snapshot-" + "a" * 64,
            "market": {"snapshot_id": "a" * 64},
            "candidates": [],
        },
    )

    result = _read_decision(
        {
            "fresh": True,
            "local_date": "2026-08-07",
            "snapshot_id": "a" * 64,
        }
    )

    assert result["available"] is False
    assert result["run_id"] is None
