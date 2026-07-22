import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from utils.probability_model import (
    BinaryLogit,
    ModelFitError,
    binary_auc,
    population_stability_index,
    probability_metrics,
)


class ProbabilityModelTest(unittest.TestCase):
    def test_fit_predict_and_round_trip(self):
        frame = pd.DataFrame({"x": np.linspace(-2, 2, 100)})
        frame["y"] = (frame["x"] > 0).astype(int)
        model = BinaryLogit(["x"]).fit(frame, "y")
        before = model.predict_proba(frame)
        restored = BinaryLogit.from_dict(model.to_dict())
        after = restored.predict_proba(frame)
        self.assertGreater(binary_auc(frame["y"], before), 0.95)
        np.testing.assert_allclose(before, after)

    def test_constant_target_is_supported(self):
        frame = pd.DataFrame({"x": [1, 2, 3], "y": [0, 0, 0]})
        model = BinaryLogit(["x"]).fit(frame, "y")
        probability = model.predict_proba(frame)
        self.assertTrue(np.all(probability < 0.01))
        self.assertFalse(model.training_diagnostics["releaseable"])
        self.assertEqual(model.training_diagnostics["optimizer_status"], "single_class")

    @patch("utils.probability_model.minimize")
    def test_optimizer_failure_is_not_silently_replaced_by_zero_model(self, minimize):
        result = type(
            "Result",
            (),
            {
                "success": False,
                "x": np.zeros(2),
                "status": 2,
                "message": "line search failed",
                "nit": 3,
                "jac": np.array([1.0, 1.0]),
                "fun": 1.0,
            },
        )()
        minimize.return_value = result
        frame = pd.DataFrame({"x": [-1.0, 1.0], "y": [0, 1]})

        with self.assertRaisesRegex(ModelFitError, "优化失败"):
            BinaryLogit(["x"]).fit(frame, "y")

    def test_extreme_features_stay_finite(self):
        frame = pd.DataFrame({"x": [0.0, 1e300, -1e300, 3.0], "y": [0, 1, 0, 1]})
        model = BinaryLogit(["x"]).fit(frame, "y")
        self.assertTrue(np.isfinite(model.coef).all())
        self.assertTrue(np.isfinite(model.predict_proba(frame)).all())

    def test_copy_on_write_frame_does_not_raise_read_only_assignment(self):
        # pandas >=3 始终启用 Copy-on-Write；无需再设置已弃用的全局选项。
        frame = pd.DataFrame({"x": [1.0, np.inf, 3.0], "y": [0, 1, 0]})
        probability = BinaryLogit(["x"]).fit(frame, "y").predict_proba(frame)

        self.assertTrue(np.isfinite(probability).all())

    def test_probability_metrics_include_calibration_curve(self):
        metrics = probability_metrics(
            [0, 0, 1, 1],
            [0.1, 0.2, 0.8, 0.9],
        )

        self.assertIsNotNone(metrics["brier"])
        self.assertIsNotNone(metrics["expected_calibration_error"])
        self.assertGreaterEqual(len(metrics["calibration_curve"]), 2)
        self.assertEqual(sum(item["count"] for item in metrics["calibration_curve"]), 4)

    def test_population_stability_index_detects_feature_drift_and_missingness(self):
        reference = pd.DataFrame({"x": np.linspace(0, 1, 200)})
        current = pd.DataFrame({"x": [np.nan] * 50 + list(np.linspace(5, 6, 150))})

        drift = population_stability_index(reference, current, ["x"])

        self.assertFalse(drift["releaseable"])
        self.assertEqual(drift["features"]["x"]["status"], "drifted")
        self.assertEqual(drift["features"]["x"]["current_missing_rate"], 0.25)


if __name__ == "__main__":
    unittest.main()
