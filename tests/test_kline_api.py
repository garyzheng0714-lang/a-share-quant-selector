import unittest
from unittest.mock import patch

import pandas as pd

from web_server import app


def _weekly_source() -> pd.DataFrame:
    dates = list(pd.date_range("2025-01-03", periods=62, freq="W-FRI"))
    dates.append(dates[-1] + pd.Timedelta(days=5))
    rows = []
    for index, date in enumerate(dates, start=1):
        close = 10 + index * 0.1
        rows.append({
            "date": date, "open": close - 0.05, "close": close,
            "high": close + 0.1, "low": close - 0.1,
            "volume": 1000 + index, "amount": 0, "turnover": 0,
            "market_cap": 1e10,
        })
    return pd.DataFrame(rows).sort_values("date", ascending=False).reset_index(drop=True)


class KlineApiTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    @patch("web_server._load_stock_names", return_value={"600000": "浦发银行"})
    @patch("web_server.csv_manager.read_stock", return_value=_weekly_source())
    def test_weekly_contract_exposes_four_ma_and_partial_week(self, _read, _names):
        response = self.client.get("/api/stock/600000/kline?period=weekly")

        self.assertEqual(response.status_code, 200)
        payload = response.json
        self.assertEqual(payload["change_label"], "本周涨跌")
        self.assertTrue(payload["current_week_partial"])
        self.assertEqual(payload["as_of"], "2026-03-11")
        self.assertEqual(payload["week_end"], "2026-03-13")
        self.assertTrue(all(value is not None for value in payload["data"][-1][6:10]))

    def test_invalid_period_is_rejected(self):
        response = self.client.get("/api/stock/600000/kline?period=monthly")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
