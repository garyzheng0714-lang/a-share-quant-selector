import unittest

from utils.policy_engine import evaluate_policy, policy_manifest


class PolicyEngineTest(unittest.TestCase):
    def _manifest(self, weekly="shadow"):
        return policy_manifest(
            policy_version="p1",
            weekly_gate_mode=weekly,
            strict_unvalidated_market=False,
            top_n=1,
            components={
                "market": {"mode": "active", "threshold": 0.5, "version": "m1"},
                "sector": {"mode": "active", "threshold": 0.5, "version": "m1"},
                "entry_risk": {"mode": "active", "threshold": 0.4, "version": "m1"},
                "exit_risk": {"mode": "active", "threshold": 0.4, "version": "m1"},
                "quality": {"mode": "active", "version": "m1"},
            },
        )

    def test_weekly_shadow_does_not_change_runtime_action(self):
        candidate = {
            "candidate_id": "1",
            "code": "600000",
            "decision_date": "2026-01-05",
            "weekly_passed": False,
            "probabilities": {
                "market": 0.8,
                "sector": 0.8,
                "entry_risk": 0.1,
                "exit_risk": 0.1,
                "quality": 0.8,
            },
        }

        result = evaluate_policy([candidate], self._manifest())[0]

        self.assertEqual(result["action"], "buy")
        self.assertIn("weekly_four_ma_shadow_fail", result["reason_codes"])

    def test_entry_and_exit_fill_risks_are_separate_vetoes(self):
        common = {
            "decision_date": "2026-01-05",
            "weekly_passed": True,
            "probabilities": {"market": 0.8, "sector": 0.8, "quality": 0.8},
        }
        rows = [
            {
                **common,
                "candidate_id": "entry",
                "code": "600000",
                "probabilities": {
                    **common["probabilities"],
                    "entry_risk": 0.9,
                    "exit_risk": 0.1,
                },
            },
            {
                **common,
                "candidate_id": "exit",
                "code": "600001",
                "probabilities": {
                    **common["probabilities"],
                    "entry_risk": 0.1,
                    "exit_risk": 0.9,
                },
            },
        ]

        result = {
            row["candidate_id"]: row for row in evaluate_policy(rows, self._manifest())
        }

        self.assertIn("entry_fill_risk_veto", result["entry"]["reason_codes"])
        self.assertIn("exit_fill_risk_veto", result["exit"]["reason_codes"])


if __name__ == "__main__":
    unittest.main()
