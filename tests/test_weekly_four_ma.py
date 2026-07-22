import unittest

import pandas as pd

from utils.technical import weekly_four_ma_bullish


def _weekly_frame(closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2025-01-03", periods=len(closes), freq="W-FRI"),
            "close": closes,
        }
    )


class WeeklyFourMaTest(unittest.TestCase):
    def test_exposes_each_line_direction(self):
        frame = _weekly_frame([float(value) for value in range(1, 63)])
        passed, detail = weekly_four_ma_bullish(frame)

        self.assertTrue(passed)
        self.assertTrue(detail["aligned"])
        self.assertTrue(detail["rising"])
        self.assertEqual(detail["rising_count"], 4)
        self.assertEqual(
            detail["directions"],
            {
                "MA5": True,
                "MA10": True,
                "MA20": True,
                "MA60": True,
            },
        )
        self.assertEqual(detail["as_of"], str(frame["date"].iloc[-1].date()))
        self.assertFalse(detail["current_week_partial"])

    def test_exposes_downward_lines(self):
        closes = [float(value) for value in range(1, 62)] + [-100.0]
        passed, detail = weekly_four_ma_bullish(_weekly_frame(closes))

        self.assertFalse(passed)
        self.assertFalse(detail["rising"])
        self.assertEqual(detail["rising_count"], 0)
        self.assertTrue(
            all(rising is False for rising in detail["directions"].values())
        )


if __name__ == "__main__":
    unittest.main()
