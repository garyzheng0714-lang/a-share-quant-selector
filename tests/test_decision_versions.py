from pathlib import Path
from unittest.mock import patch

from utils import decision_versions


def test_strategy_version_dependency_set_covers_policy_execution_and_locks():
    relative = {
        path.relative_to(decision_versions.PROJECT_ROOT).as_posix()
        for path in decision_versions._policy_files()
    }

    assert {
        "utils/execution_model.py",
        "utils/hierarchical_decision.py",
        "utils/decision_ledger.py",
        "utils/csv_manager.py",
        "utils/policy_engine.py",
        "utils/market_filter.py",
        "utils/factor_scan.py",
        "utils/market_snapshot.py",
        "tools/hierarchical_walk_forward.py",
        "config/strategy_params.yaml",
        "requirements.in",
        "requirements.lock",
        "frontend/package-lock.json",
        "strategy/factors/b1_family.py",
    }.issubset(relative)


def test_strategy_version_changes_when_dependency_content_changes(tmp_path):
    root = Path(tmp_path)
    strategy = root / "strategy"
    config = root / "config"
    strategy.mkdir()
    config.mkdir()
    (strategy / "rule.py").write_text("threshold = 1\n", encoding="utf-8")
    params = config / "strategy_params.yaml"
    params.write_text("threshold: 1\n", encoding="utf-8")

    with (
        patch.object(decision_versions, "PROJECT_ROOT", root),
        patch.object(decision_versions, "BASELINE_FILES", ()),
    ):
        first = decision_versions.strategy_version()
        params.write_text("threshold: 2\n", encoding="utf-8")
        second = decision_versions.strategy_version()

    assert first != second


def test_strategy_version_changes_when_policy_engine_changes(tmp_path):
    root = Path(tmp_path)
    policy_engine = root / "utils" / "policy_engine.py"
    policy_engine.parent.mkdir()
    policy_engine.write_text("decision = 'hold'\n", encoding="utf-8")

    with (
        patch.object(decision_versions, "PROJECT_ROOT", root),
        patch.object(decision_versions, "BASELINE_FILES", (policy_engine,)),
    ):
        first = decision_versions.strategy_version()
        policy_engine.write_text("decision = 'buy'\n", encoding="utf-8")
        second = decision_versions.strategy_version()

    assert first != second
