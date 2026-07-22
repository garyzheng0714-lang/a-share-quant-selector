import unittest
from unittest.mock import patch

from utils.decision_replay import replay_decision
from utils.policy_engine import policy_manifest


class DecisionReplayTest(unittest.TestCase):
    def test_same_snapshot_and_manifest_replay_exactly(self):
        snapshot_id = "a" * 64
        policy = policy_manifest(
            policy_version="p1",
            weekly_gate_mode="shadow",
            strict_unvalidated_market=False,
            top_n=3,
            components={
                "market": {"mode": "active", "threshold": 0.5},
                "sector": {"mode": "off"},
                "entry_risk": {"mode": "off"},
                "exit_risk": {"mode": "off"},
                "quality": {"mode": "off"},
            },
        )
        decision = {
            "run_id": "run-1",
            "stage": "close",
            "trade_date": "2026-01-05",
            "as_of": "2026-01-05T15:05:00+08:00",
            "data_version": f"snapshot-{snapshot_id}",
            "market": {"snapshot_id": snapshot_id, "policy_manifest": policy},
            "candidates": [
                {
                    "code": "600000",
                    "action": "buy",
                    "rank": 1,
                    "reason_codes": ["weekly_four_ma_shadow_fail"],
                    "baseline": {"weekly": {"passed": False}},
                    "market": {"probability": 0.8},
                    "sector": {},
                    "stock": {},
                }
            ],
        }
        snapshot = {
            "available": True,
            "manifest": {
                "trade_date": "2026-01-05",
                "closed_at": "2026-01-05T15:05:00+08:00",
            },
        }
        with (
            patch("utils.decision_replay.load_market_snapshot", return_value=snapshot),
            patch("utils.decision_replay.get_decision", return_value=decision),
        ):
            result = replay_decision("run-1", snapshot_id)

        self.assertTrue(result["available"])
        self.assertTrue(result["parity"])

    def test_snapshot_mismatch_is_rejected(self):
        snapshot_id = "a" * 64
        with (
            patch(
                "utils.decision_replay.load_market_snapshot",
                return_value={
                    "available": True,
                    "manifest": {
                        "trade_date": "2026-01-05",
                        "closed_at": "2026-01-05T15:05:00+08:00",
                    },
                },
            ),
            patch(
                "utils.decision_replay.get_decision",
                return_value={
                    "stage": "close",
                    "trade_date": "2026-01-05",
                    "as_of": "2026-01-05T15:05:00+08:00",
                    "data_version": "snapshot-other",
                    "market": {"snapshot_id": "other"},
                    "candidates": [],
                },
            ),
        ):
            result = replay_decision("run-1", snapshot_id)

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "decision_snapshot_mismatch")


if __name__ == "__main__":
    unittest.main()
