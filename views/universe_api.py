"""全量股票池覆盖率与后台历史回补 API。"""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)
universe_bp = Blueprint("universe", __name__)
_thread: threading.Thread | None = None
_thread_lock = threading.Lock()


def _run_bootstrap() -> None:
    lock_file = None
    try:
        import fcntl
        from utils.akshare_fetcher import AKShareFetcher

        lock_path = Path("data/.universe_bootstrap.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path.open("w")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = AKShareFetcher("data").bootstrap_universe(
            max_stocks=None, years=6, refresh_universe=True,
        )
        logger.info("全量股票池回补结束: %s", result)
    except BlockingIOError:
        logger.info("已有其他进程执行全量股票池回补")
    except Exception as exc:
        logger.error("全量股票池回补失败: %s", exc, exc_info=True)
    finally:
        if lock_file is not None:
            lock_file.close()


def start_universe_bootstrap() -> bool:
    """幂等启动后台全量任务；不阻塞 Web 请求和生产部署。"""
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return False
        _thread = threading.Thread(target=_run_bootstrap, name="universe-bootstrap", daemon=True)
        _thread.start()
        return True


@universe_bp.route("/api/data/coverage", methods=["GET"])
def api_data_coverage():
    from utils.akshare_fetcher import AKShareFetcher
    status = AKShareFetcher("data").universe_coverage()
    status["running"] = bool(_thread and _thread.is_alive())
    return jsonify({"success": True, "data": status})


@universe_bp.route("/api/data/bootstrap", methods=["POST"])
def api_data_bootstrap():
    started = start_universe_bootstrap()
    return jsonify({"success": True, "started": started,
                    "message": "全量回补已启动" if started else "全量回补正在运行"})
