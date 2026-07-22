"""唯一的生产策略门禁引擎。

这个模块不读文件、不查数据库、不看墙上时间；相同证据和 manifest
必须得到字节级稳定的动作。生产、历史 replay 和 walk-forward 共用它。
"""

from __future__ import annotations

from copy import deepcopy


MODEL_COMPONENTS = ("market", "sector", "entry_risk", "exit_risk", "quality")


def policy_manifest(
    *,
    policy_version: str,
    weekly_gate_mode: str,
    components: dict[str, dict],
    strict_unvalidated_market: bool,
    top_n: int = 3,
) -> dict:
    if weekly_gate_mode not in {"off", "shadow", "active"}:
        raise ValueError("weekly_gate_mode 非法")
    if top_n < 1:
        raise ValueError("top_n 必须大于 0")
    normalized = {}
    for key in MODEL_COMPONENTS:
        item = components.get(key) or {}
        mode = item.get("mode", "off")
        if mode not in {"off", "shadow", "active"}:
            raise ValueError(f"{key}.mode 非法")
        normalized[key] = {
            "mode": mode,
            "threshold": item.get("threshold"),
            "version": item.get("version"),
        }
    return {
        "schema_version": "canonical-policy-v1",
        "policy_version": policy_version,
        "weekly_gate": {"mode": weekly_gate_mode, "version": "weekly-four-ma-v2"},
        "components": normalized,
        "strict_unvalidated_market": bool(strict_unvalidated_market),
        "top_n": int(top_n),
        "gate_order": [
            "weekly_four_ma",
            "market",
            "sector",
            "entry_risk",
            "exit_risk",
            "quality",
        ],
    }


def _failed_probability_gate(probability, threshold, *, keep_high: bool) -> bool:
    if not isinstance(probability, (int, float)) or not isinstance(
        threshold, (int, float)
    ):
        return True
    return probability < threshold if keep_high else probability > threshold


def _score(item: dict, key: str) -> float:
    value = (item.get("probabilities") or {}).get(key)
    return float(value) if isinstance(value, (int, float)) else float("-inf")


def evaluate_policy(candidates: list[dict], manifest: dict) -> list[dict]:
    """根据冻结证据返回 action/reason/rank，不改动输入。"""
    if manifest.get("schema_version") != "canonical-policy-v1":
        raise ValueError("不支持的 policy manifest")
    components = manifest.get("components") or {}
    results = []
    for original in candidates:
        item = deepcopy(original)
        reasons = list(item.get("reason_codes") or [])
        probabilities = item.get("probabilities") or {}
        action = "buy"

        market_mode = (components.get("market") or {}).get("mode", "off")
        if manifest.get("strict_unvalidated_market") and market_mode != "active":
            action = "observe"
            reasons.append("market_model_unvalidated")

        weekly_mode = (manifest.get("weekly_gate") or {}).get("mode", "off")
        if item.get("weekly_passed") is not True:
            if weekly_mode == "active":
                action = "observe"
                reasons.append("weekly_four_ma_gate")
            elif weekly_mode == "shadow":
                reasons.append("weekly_four_ma_shadow_fail")

        gates = (
            ("market", True, "market_gate"),
            ("sector", True, "sector_gate"),
            ("entry_risk", False, "entry_fill_risk_veto"),
            ("exit_risk", False, "exit_fill_risk_veto"),
        )
        for key, keep_high, reason in gates:
            component = components.get(key) or {}
            if (
                action == "buy"
                and component.get("mode") == "active"
                and _failed_probability_gate(
                    probabilities.get(key),
                    component.get("threshold"),
                    keep_high=keep_high,
                )
            ):
                action = "avoid"
                reasons.append(reason)
                break
        item["action"] = action
        item["reason_codes"] = sorted(set(reasons))
        results.append(item)

    top_n = int(manifest.get("top_n", 3))
    quality_mode = (components.get("quality") or {}).get("mode", "off")
    by_date: dict[str, list[dict]] = {}
    for item in results:
        if item["action"] == "buy":
            by_date.setdefault(str(item.get("decision_date") or ""), []).append(item)
    for rows in by_date.values():
        if len(rows) <= top_n:
            continue
        if quality_mode == "active":
            ranked = sorted(
                rows,
                key=lambda row: (
                    -_score(row, "quality"),
                    str(row.get("code") or row.get("candidate_id") or ""),
                ),
            )
            keep_ids = {id(row) for row in ranked[:top_n]}
            for row in rows:
                if id(row) not in keep_ids:
                    row["action"] = "observe"
                    row["reason_codes"] = sorted(
                        set(
                            [
                                *row["reason_codes"],
                                "outside_top_n",
                            ]
                        )
                    )
        else:
            for row in rows:
                row["action"] = "observe"
                row["reason_codes"] = sorted(
                    set(
                        [
                            *row["reason_codes"],
                            "unresolved_tie_over_top_n",
                        ]
                    )
                )

    results.sort(
        key=lambda item: (
            {"buy": 0, "observe": 1, "avoid": 2}[item["action"]],
            -_score(item, "quality"),
            str(item.get("code") or item.get("candidate_id") or ""),
        )
    )
    for index, item in enumerate(results, start=1):
        item["rank"] = index
        item["tie_group"] = 1 if item["action"] == "buy" else index
    return results
