from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_production_canary_has_no_port_and_only_read_only_data_mounts() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    canary = compose["services"]["canary"]

    assert canary["profiles"] == ["canary"]
    assert canary["restart"] == "no"
    assert canary["read_only"] is True
    assert "ports" not in canary
    assert canary["volumes"] == [
        "quant-data:/app/data:ro",
        "quant-state:/app/state:ro",
    ]


def test_release_quiesces_writers_and_validates_canary_before_switch() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    deploy_steps = workflow["jobs"]["deploy"]["steps"]
    release_step = next(
        step for step in deploy_steps if step.get("name", "").startswith("Deploy exact")
    )
    script = release_step["run"]

    expected_order = (
        "stop worker web",
        "python tools/backup_databases.py",
        "python tools/migration_dry_run.py",
        "run --rm --no-deps migrate",
        "python tools/predeploy_check.py",
        '--name "$CANARY_NAME" --no-deps canary',
        "mv .release.env.next .release.env",
    )
    positions = [script.index(fragment) for fragment in expected_order]
    assert positions == sorted(positions)
    assert "cleanup_canary" in script
    assert "PREVIOUS_STOPPED" in script
    assert "docker inspect -f '{{.Config.Image}}' \"$CANARY_NAME\"" in script
    assert "for attempt in $(seq 1 30)" in script


def test_release_stages_image_before_transactional_deploy() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    deploy = workflow["jobs"]["deploy"]
    deploy_steps = deploy["steps"]
    stage_index = next(
        index
        for index, step in enumerate(deploy_steps)
        if step.get("name") == "Stage exact image digest on server"
    )
    release_index = next(
        index
        for index, step in enumerate(deploy_steps)
        if step.get("name", "").startswith("Deploy exact")
    )
    stage_step = deploy_steps[stage_index]
    release_step = deploy_steps[release_index]
    stage_script = stage_step["run"]
    release_script = release_step["run"]

    assert deploy["timeout-minutes"] == 90
    assert stage_index < release_index
    assert stage_step["timeout-minutes"] == 60
    assert release_step["timeout-minutes"] == 25
    assert "docker pull '$IMAGE@$DIGEST'" in stage_script
    assert "docker image inspect '$IMAGE@$DIGEST'" in stage_script
    assert "docker compose --env-file .release.env.next pull" not in release_script
    assert 'docker image inspect "${IMAGE}@${DIGEST}"' in release_script
    assert "restore_before_switch 130" in release_script
    assert "interrupt_after_switch" in release_script
