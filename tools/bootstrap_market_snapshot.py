#!/usr/bin/env python3
"""首次生产发布前构建可验证的行情快照。

该命令只在独立的发布前容器中运行。已有完整且新鲜的快照时会直接复用；
若已有完整但过期的验证快照，优先做日更；否则从可信外部源全量重建，
不读取或升格 legacy CSV。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def snapshot_status(data_dir: Path) -> dict[str, Any]:
    """同时校验内容哈希和交易日新鲜度。"""
    from utils.csv_manager import CSVManager
    from utils.data_freshness import local_data_status
    from utils.market_snapshot import load_current_market_snapshot

    snapshot = load_current_market_snapshot(data_dir, verify_files=True)
    if not snapshot.get("available"):
        return {
            "ready": False,
            "reason": snapshot.get("reason", "validated_snapshot_missing"),
            "snapshot_id": None,
        }
    freshness = local_data_status(CSVManager(data_dir, writable=False))
    return {
        "ready": freshness.get("fresh") is True,
        "reason": freshness.get("reason"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "trade_date": (snapshot.get("manifest") or {}).get("trade_date"),
        "expected_date": freshness.get("expected_date"),
        "coverage_ratio": freshness.get("coverage_ratio"),
        "source_set": freshness.get("source_set") or [],
    }


def _rebuild_summary(result: dict[str, Any]) -> dict[str, Any]:
    """不把数千个股票的失败明细全部打进发布日志。"""
    bootstrap = result.get("bootstrap") or {}
    quality = result.get("quality") or {}
    return {
        "success": result.get("success") is True,
        "reason": result.get("reason"),
        "snapshot_id": result.get("snapshot_id"),
        "trade_date": result.get("trade_date"),
        "staging_dir": result.get("staging_dir"),
        "resumed_staging": result.get("resumed_staging") is True,
        "universe_count": result.get("universe_count"),
        "universe_status": result.get("universe_status"),
        "universe_seed": result.get("universe_seed"),
        "bootstrap": {
            key: bootstrap.get(key)
            for key in (
                "status",
                "universe_count",
                "attempted",
                "added",
                "failed",
                "coverage_ratio",
                "remaining_count",
                "pass_count",
                "failure_reason_counts",
                "passes",
                "source_quorum",
            )
            if key in bootstrap
        },
        "quality": {
            "valid": quality.get("valid"),
            "expected_count": quality.get("expected_count"),
            "valid_count": quality.get("valid_count"),
            "coverage_ratio": quality.get("coverage_ratio"),
            "source_set": quality.get("source_set"),
            "schema_error_count": quality.get("schema_error_count"),
            "missing_code_count": len(quality.get("missing_codes") or []),
            "stale_code_count": len(quality.get("stale_codes") or {}),
            "reference_valid": (quality.get("reference_quality") or {}).get("valid"),
            "security_status_valid": (quality.get("security_status_quality") or {}).get(
                "valid"
            ),
        },
    }


def _daily_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": result.get("success") is True,
        "reason": result.get("reason"),
        "snapshot_id": result.get("snapshot_id"),
        "trade_date": result.get("trade_date"),
        "staging_dir": result.get("staging_dir"),
        "universe_count": result.get("universe_count"),
        "universe_status": result.get("universe_status"),
        "detail": result.get("detail"),
        "error_type": result.get("error_type"),
    }


def _arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--years", type=int, default=6, choices=range(1, 11))
    parser.add_argument("--check-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _arguments(argv)
    status = snapshot_status(args.data_dir)
    print(json.dumps({"stage": "current_snapshot", **status}, ensure_ascii=False))
    if status["ready"]:
        return 0
    if args.check_only:
        return 3

    # 已有完整验证快照但交易日过期时，优先日更；全量重建成本高且空 staging
    # 没有 LKG 名单，东财一断就会 approved_universe_unavailable。
    if status.get("snapshot_id"):
        from utils.market_ingestion import run_daily_ingestion

        daily = run_daily_ingestion(args.data_dir)
        print(
            json.dumps(
                {"stage": "daily_ingestion", **_daily_summary(daily)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        if daily.get("success") is True:
            final_status = snapshot_status(args.data_dir)
            print(
                json.dumps(
                    {"stage": "final_snapshot", **final_status},
                    ensure_ascii=False,
                )
            )
            return 0 if final_status["ready"] else 1
        print(
            "Daily ingestion did not produce a fresh snapshot "
            f"({daily.get('reason')}); falling back to trusted full rebuild.",
            file=sys.stderr,
        )

    from utils.market_ingestion import run_full_rebuild

    result = run_full_rebuild(args.data_dir, years=args.years)
    print(
        json.dumps(
            {"stage": "trusted_full_rebuild", **_rebuild_summary(result)},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if result.get("success") is not True:
        return 1

    final_status = snapshot_status(args.data_dir)
    print(json.dumps({"stage": "final_snapshot", **final_status}, ensure_ascii=False))
    return 0 if final_status["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
