"""因子结果证据边界测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from utils.factor_evidence import (
    _apply_removal_evidence,
    _daily_history_by_code,
    _first_removal_date,
    _observation_status,
)
from utils.strategy_intelligence import _summarize_window


def test_removed_code_uses_last_verified_snapshot_history(tmp_path, monkeypatch):
    snapshot_id = "a" * 64
    payload = tmp_path / "market_snapshots" / snapshot_id / "payload"
    stock_dir = payload / "60"
    stock_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "date": "2026-01-05",
                "open": 10.0,
                "high": 10.2,
                "low": 9.8,
                "close": 10.0,
                "volume": 100,
            },
            {
                "date": "2026-01-06",
                "open": 10.1,
                "high": 10.3,
                "low": 10.0,
                "close": 10.2,
                "volume": 100,
            },
        ]
    ).to_csv(stock_dir / "600000.csv", index=False)
    current = SimpleNamespace(
        base_data_dir=tmp_path,
        data_dir=tmp_path / "current",
        snapshot_id="b" * 64,
        read_stock=lambda _code: pd.DataFrame(),
    )
    snapshots = {
        "2026-01-06": {
            "market_snapshot_id": snapshot_id,
            "universe": ["600000"],
            "_universe_set": {"600000"},
        }
    }
    monkeypatch.setattr(
        "utils.reference_snapshots.validated_snapshot_payload",
        lambda _snapshot, _root, _snapshot_id: payload,
    )

    daily, sources = _daily_history_by_code(
        current, {"600000"}, "2026-01-07", snapshots
    )

    assert daily["600000"]["date"].tolist() == ["2026-01-05", "2026-01-06"]
    assert sources["600000"] == snapshot_id


def test_removal_only_closes_known_entry_inside_terminal_window():
    snapshots = {
        "2026-01-06": {
            "universe": ["600000"],
            "_universe_set": {"600000"},
            "security_states": {"600000": {"trading_status": "active"}},
        },
        "2026-01-08": {
            "universe": [],
            "_universe_set": set(),
            "security_states": {},
        },
    }
    assert _first_removal_date(snapshots, "600000", "2026-01-05", "2026-01-07") is None
    removal_date = _first_removal_date(snapshots, "600000", "2026-01-05", "2026-01-08")
    assert removal_date == "2026-01-08"

    entered = _apply_removal_evidence(
        {
            "entry_label_mature": True,
            "entry_feasible": True,
            "exit_label_mature": False,
            "return_label_mature": False,
        },
        removal_date,
    )
    assert entered["execution_status"] == "universe_removed_before_label"
    assert entered["exit_feasible"] is False
    assert _observation_status(entered) == "invalid"

    unknown = _apply_removal_evidence(
        {
            "entry_label_mature": False,
            "entry_feasible": None,
            "exit_label_mature": False,
            "return_label_mature": False,
        },
        removal_date,
    )
    assert unknown["execution_status"] == "universe_removed_with_entry_unknown"
    assert unknown["entry_feasible"] is None
    assert _observation_status(unknown) == "pending"


def test_overdue_pending_day_blocks_shadow_ranking_without_backfill_substitution():
    signal_dates = pd.bdate_range("2026-01-05", periods=61).strftime("%Y-%m-%d")
    records = [
        {
            "pick_date": day,
            "net_return": 1.0,
            "max_drawdown": -0.5,
            "evidence_tier": "pit_verified",
        }
        for day in signal_dates[:-1]
    ]

    summary = _summarize_window(
        records,
        pending_dates=[signal_dates[-1]],
        overdue_pending_dates=[signal_dates[-1]],
    )

    # 最近 60 个原始信号日包含这个逾期日，不用第 61 个更早样本补位。
    assert summary["sample_count"] == 59
    assert summary["pending_signal_day_count"] == 1
    assert summary["overdue_pending_signal_day_count"] == 1
    assert summary["evidence_complete"] is False
