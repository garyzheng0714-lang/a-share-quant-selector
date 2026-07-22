#!/usr/bin/env python3
"""生产运维 CLI。

长任务一律进入持久任务队列，由独立 worker 执行。旧 BowlRebound CLI 已移到
``research/legacy``，不会再写生产 decision/performance 账本。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Shanghai")


def _enqueue(task_type: str, key: str, payload: dict | None = None) -> int:
    from utils.operations_store import TaskQueueCapacityExceeded, enqueue_task
    from utils.runtime_schema import verify_runtime_schema

    verify_runtime_schema()
    try:
        task, created = enqueue_task(
            task_type,
            key,
            payload=payload or {},
            requested_by=f"local-cli:{os.environ.get('USER', 'unknown')}",
            change_reason="explicit local production CLI request",
        )
    except TaskQueueCapacityExceeded as exc:
        print(
            json.dumps(
                {
                    "created": False,
                    "error": "task_queue_capacity_exceeded",
                    "pending": exc.pending,
                    "limit": exc.limit,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    print(json.dumps({"created": created, "task": task}, ensure_ascii=False, indent=2))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A-Share Quant Selector 生产运维入口")
    parser.add_argument("--verbose", action="store_true")
    commands = parser.add_subparsers(dest="command", required=True)

    web = commands.add_parser("web", help="启动只读 Web/API 进程")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=5000)

    commands.add_parser("worker", help="启动唯一调度 leader 与持久任务 worker")
    commands.add_parser("migrate", help="显式迁移并校验生产数据库")

    close = commands.add_parser("enqueue-close", help="提交完整收盘 DAG")
    close.add_argument("--trade-date", default=datetime.now(TZ).date().isoformat())

    ingestion = commands.add_parser("enqueue-ingestion", help="提交每日行情快照任务")
    ingestion.add_argument("--trade-date", default=datetime.now(TZ).date().isoformat())

    rebuild = commands.add_parser("enqueue-rebuild", help="提交全量可信行情重建")
    rebuild.add_argument("--years", type=int, default=6, choices=range(1, 11))
    rebuild.add_argument("--key", help="显式幂等键；默认按日期和年数生成")

    commands.add_parser("legacy-location", help="仅显示隔离后的旧研究 CLI 路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)
    os.chdir(PROJECT_ROOT)

    if args.command == "web":
        from web_server import run_web_server

        run_web_server(host=args.host, port=args.port)
        return 0
    if args.command == "worker":
        from worker import run_worker

        run_worker()
        return 0
    if args.command == "migrate":
        from utils.runtime_schema import migrate_runtime_schema

        result = migrate_runtime_schema()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    if args.command == "enqueue-close":
        return _enqueue(
            "daily_close_pipeline",
            f"manual-close:{args.trade_date}",
            {"trade_date": args.trade_date},
        )
    if args.command == "enqueue-ingestion":
        return _enqueue(
            "daily_market_ingestion",
            f"manual-ingestion:{args.trade_date}",
            {"trade_date": args.trade_date},
        )
    if args.command == "enqueue-rebuild":
        key = (
            args.key
            or f"manual-rebuild:{datetime.now(TZ).date().isoformat()}:{args.years}y"
        )
        return _enqueue("full_market_rebuild", key, {"years": args.years})
    if args.command == "legacy-location":
        print(PROJECT_ROOT / "research" / "legacy" / "bowl_rebound_cli.py")
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
