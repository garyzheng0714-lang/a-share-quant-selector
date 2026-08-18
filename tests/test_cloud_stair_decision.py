from types import SimpleNamespace

from utils.cloud_stair_decision import _cap_yi, load_cloud_stair_decision


def test_cap_yi_prefers_circ_mv():
    assert _cap_yi("002141", {"002141": {"circ_mv": 5.34e9, "total_mv": 9e9}}) == 53.4
    assert _cap_yi("002141", {"002141": {"total_mv": 2.1e9}}) == 21.0
    assert _cap_yi("002141", {}) is None
    assert _cap_yi("002141", {"002141": {"circ_mv": 0}}) is None


def test_load_cloud_stair_decision_attaches_snapshot_cap(monkeypatch):
    manager = SimpleNamespace(base_data_dir="data", snapshot_id="snap-1")
    monkeypatch.setattr(
        "utils.factor_scan.read_cached_factor_hits",
        lambda *_args, **_kwargs: {
            "available": True,
            "trade_date": "2026-08-18",
            "results": {
                "cloud_stair": {
                    "hits": [{"code": "002141", "name": "贤丰控股", "close": 7.18}]
                }
            },
        },
    )
    monkeypatch.setattr(
        "utils.cloud_stair_decision.read_snapshot_metadata",
        lambda filename, *_args, **_kwargs: (
            (
                {"002141": "元件"}
                if filename == "stock_industry.json"
                else {"002141": {"circ_mv": 5340000000.0, "total_mv": 5340000000.0}}
            ),
            "snap-1",
        ),
    )
    monkeypatch.setattr(
        "utils.cloud_stair_decision._sector_rotation",
        lambda _manager: {"available": True, "heat_map": {}, "hot": []},
    )
    monkeypatch.setattr("utils.market_filter.main_board_only", lambda: False)

    result = load_cloud_stair_decision(manager)

    assert result["available"] is True
    assert result["candidates"][0]["cap_yi"] == 53.4
