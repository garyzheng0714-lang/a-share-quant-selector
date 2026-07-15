import unittest

import numpy as np
import pandas as pd

from utils.probability_model import BinaryLogit, binary_auc


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
        probability = BinaryLogit(["x"]).fit(frame, "y").predict_proba(frame)
        self.assertTrue(np.all(probability < 0.01))

    def test_extreme_features_stay_finite(self):
        frame = pd.DataFrame({"x": [0.0, 1e300, -1e300, 3.0], "y": [0, 1, 0, 1]})
        model = BinaryLogit(["x"]).fit(frame, "y")
        self.assertTrue(np.isfinite(model.coef).all())
        self.assertTrue(np.isfinite(model.predict_proba(frame)).all())


if __name__ == "__main__":
    unittest.main()
