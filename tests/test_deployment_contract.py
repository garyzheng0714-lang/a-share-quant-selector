from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_production_canary_has_no_port_and_only_read_only_data_mounts() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    canary = compose["services"]["canary"]

    assert compose["x-quant-common"]["pull_policy"] == "never"
    assert canary["profiles"] == ["canary"]
    assert canary["restart"] == "no"
    assert canary["read_only"] is True
    assert "ports" not in canary
    assert canary["volumes"] == [
        "quant-data:/app/data:ro",
        "quant-state:/app/state:ro",
    ]
    assert canary["tmpfs"] == ["/tmp:size=2g,noexec,nosuid,nodev"]


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
        "--no-deps web python tools/backup_databases.py",
        "--no-deps canary python tools/migration_dry_run.py",
        "--no-deps migrate </dev/null",
        "--no-deps web python tools/predeploy_check.py",
        '--name "$CANARY_NAME" --no-deps canary',
        'mv "$NEXT_ENV" .release.env',
    )
    positions = [script.index(fragment) for fragment in expected_order]
    assert positions == sorted(positions)
    assert "cleanup_canary" in script
    assert "PREVIOUS_STOPPED" in script
    assert "docker inspect -f '{{.Config.Image}}' \"$CANARY_NAME\"" in script
    assert "for attempt in $(seq 1 360)" in script


def test_release_stages_image_before_transactional_deploy() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    deploy = workflow["jobs"]["deploy"]
    deploy_steps = deploy["steps"]
    stage_index = next(
        index
        for index, step in enumerate(deploy_steps)
        if step.get("name") == "Stage verified image through SSH"
    )
    release_index = next(
        index
        for index, step in enumerate(deploy_steps)
        if step.get("name", "").startswith("Deploy exact")
    )
    bootstrap_index = next(
        index
        for index, step in enumerate(deploy_steps)
        if step.get("name") == "Bootstrap trusted market snapshot before traffic switch"
    )
    stage_step = deploy_steps[stage_index]
    bootstrap_step = deploy_steps[bootstrap_index]
    release_step = deploy_steps[release_index]
    stage_script = stage_step["run"]
    bootstrap_script = bootstrap_step["run"]
    release_script = release_step["run"]

    assert deploy["timeout-minutes"] == 360
    assert stage_index < bootstrap_index < release_index
    assert stage_step["timeout-minutes"] == 90
    assert bootstrap_step["timeout-minutes"] == 220
    assert release_step["timeout-minutes"] == 45
    assert 'docker pull "$SOURCE_IMAGE"' in stage_script
    assert 'docker save "$RUNTIME_IMAGE" | gzip -1' in stage_script
    assert '"$USER@$HOST" "docker load >/dev/null"' in stage_script
    assert "image_id=$RUNTIME_IMAGE_ID" in stage_script
    assert "tools/bootstrap_market_snapshot.py" in bootstrap_script
    assert "--check-only" in bootstrap_script
    assert "a-share-quant-snapshot-bootstrap" in bootstrap_script
    assert "docker inspect -f '{{.Image}}'" in bootstrap_script
    assert "run -d --interactive=false" in bootstrap_script
    ownership_init = "run --rm --interactive=false --no-deps --user 0:0"
    assert ownership_init in bootstrap_script
    assert "--cap-add CHOWN" in bootstrap_script
    assert "--cap-add DAC_OVERRIDE" in bootstrap_script
    assert "worker chown -R 10001:10001 /app/data" in bootstrap_script
    assert bootstrap_script.index("--cap-add CHOWN") < bootstrap_script.index(
        "tools/bootstrap_market_snapshot.py"
    )
    assert "docker compose --env-file .release.env.next pull" not in release_script
    assert (
        "docker image inspect --format '{{.Id}}' \"$RUNTIME_IMAGE\"" in release_script
    )
    assert "QUANT_SOURCE_IMAGE=${IMAGE}@${DIGEST}" in release_script
    assert "EXPECTED_IMAGE_ID" in release_script
    assert "restore_before_switch 130" in release_script
    assert "interrupt_after_switch" in release_script
    assert 'read_json("/api/decision/latest")' in release_script
    assert 'read_json("/api/quant-pick")' in release_script
    assert 'decision.get("available") is True' in release_script
    assert 'quant_pick.get("available") is True' in release_script


def test_empty_snapshot_check_fails_closed_without_network(tmp_path: Path) -> None:
    import json
    import subprocess
    import sys

    completed = subprocess.run(
        [
            sys.executable,
            "tools/bootstrap_market_snapshot.py",
            "--data-dir",
            str(tmp_path),
            "--check-only",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 3
    payload = json.loads(completed.stdout)
    assert payload["stage"] == "current_snapshot"
    assert payload["ready"] is False
    assert payload["reason"] == "snapshot_pointer_missing"


def test_release_one_off_containers_cannot_consume_transaction_script() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    )
    release_step = next(
        step
        for step in workflow["jobs"]["deploy"]["steps"]
        if step.get("name", "").startswith("Deploy exact")
    )
    script = release_step["run"]

    assert script.count("--interactive=false") == 5
    assert script.count("</dev/null") == 5
    assert 'DEPLOY_RECEIPT=".deploy-success-${RELEASE_SHA}"' in script
    assert 'mv "${DEPLOY_RECEIPT}.next" "$DEPLOY_RECEIPT"' in script
    assert "cat '/opt/a-share-quant/.deploy-success-${RELEASE_SHA}'" in script
