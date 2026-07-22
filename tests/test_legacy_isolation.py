import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from research.legacy.bowl_rebound_cli import _legacy_root
from research.legacy.strategy_registry import StrategyRegistry


def test_legacy_research_requires_explicit_opt_in():
    with patch.dict(
        "os.environ",
        {"LEGACY_RESEARCH_ROOT": "/tmp/legacy-quant-test"},
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="explicit_opt_in"):
            _legacy_root()


def test_legacy_research_rejects_repository_root():
    repository = Path(__file__).resolve().parents[1]
    with patch.dict(
        "os.environ",
        {
            "ALLOW_LEGACY_RESEARCH": "1",
            "LEGACY_RESEARCH_ROOT": str(repository / "legacy-output"),
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="isolated_from_repository"):
            _legacy_root()


def test_legacy_research_accepts_external_absolute_directory():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "legacy-output"
        with patch.dict(
            "os.environ",
            {
                "ALLOW_LEGACY_RESEARCH": "1",
                "LEGACY_RESEARCH_ROOT": str(root),
            },
            clear=True,
        ):
            assert _legacy_root() == root.resolve()
            assert root.is_dir()


def test_all_legacy_script_paths_stay_inside_external_root():
    from research.legacy.isolation import legacy_path

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "legacy-output"
        with patch.dict(
            "os.environ",
            {
                "ALLOW_LEGACY_RESEARCH": "1",
                "LEGACY_RESEARCH_ROOT": str(root),
            },
            clear=True,
        ):
            assert legacy_path(None, "outputs/result.json") == (
                root.resolve() / "outputs/result.json"
            )
            with pytest.raises(RuntimeError, match="inside_research_root"):
                legacy_path(str(Path(temporary).parent / "escaped.json"), "unused")


def test_production_strategy_package_does_not_export_legacy_strategy():
    import strategy

    assert strategy.STRATEGIES == {}
    assert not hasattr(strategy, "BowlReboundStrategy")
    production_root = Path(strategy.__file__).parent
    assert not (production_root / "bowl_rebound.py").exists()
    assert not (production_root / "strategy_registry.py").exists()
    assert not list(production_root.glob("pattern_*.py"))
    tools_root = production_root.parent / "tools"
    legacy_root = production_root.parent / "research" / "legacy"
    for name in (
        "resonance_backtest.py",
        "pending_backtest.py",
        "pick_ranker_research.py",
    ):
        assert not (tools_root / name).exists()
        assert (legacy_root / name).exists()


def test_production_database_module_has_no_legacy_view_crud():
    from utils import daily_pick
    from views import view_manager

    for symbol in (
        "init_db",
        "list_views",
        "get_view",
        "create_view",
        "update_view",
        "delete_view",
        "save_result",
        "get_results",
    ):
        assert not hasattr(view_manager, symbol)
    assert not hasattr(daily_pick, "init_picks_table")
    assert daily_pick.get_pick("2026-07-14") is None
    assert daily_pick.get_pick_history() == []


def test_legacy_database_is_configured_only_in_external_research_root():
    from research.legacy import view_manager as legacy_views

    original = legacy_views.DB_PATH
    try:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "legacy-output"
            database = legacy_views.configure_database(root)
            legacy_views.init_db()
            view = legacy_views.list_views()[0]
            legacy_views.save_result(
                view["id"],
                "2026-07-14",
                [{"code": "600000", "name": "浦发银行"}],
            )

            assert database == root.resolve() / "legacy_views.db"
            assert database.is_file()
    finally:
        legacy_views.DB_PATH = original


def test_legacy_tree_and_dependencies_are_absent_from_production_image():
    repository = Path(__file__).resolve().parents[1]
    ignored = {
        line.strip()
        for line in (repository / ".dockerignore")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    lock = (repository / "requirements.lock").read_text(encoding="utf-8").lower()

    assert "research" in ignored
    assert "apscheduler==" not in lock
    assert "schedule==" not in lock
    assert "fastdtw==" not in lock
    assert "matplotlib==" not in lock
    assert "utils/dingtalk_notifier.py" in ignored
    assert "utils/kline_chart.py" in ignored
    assert "utils/kline_chart_fast.py" in ignored


def test_legacy_dynamic_registry_requires_explicit_opt_in():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(RuntimeError, match="legacy_strategy_registry_disabled"):
            StrategyRegistry().auto_register_from_directory("research/legacy")
