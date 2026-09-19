import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils import cloud_stair_stock_history as history


CSV = """signal_id,code,name,exchange,board,signal_date,raw_signal_close,wave_gain_pct,T+1_能否结算,T+1_是否赚钱,T+1_扣费后%,T+1_扣费前%,T+5_能否结算,T+5_是否赚钱,T+5_扣费后%,T+5_扣费前%,T+20_能否结算,T+20_是否赚钱,T+20_扣费后%,T+20_扣费前%
a,000001,平安银行,SZSE,MAIN,2024-01-02,10,20,能,赚,1,1,能,赚,2,2,能,亏,-1,-1
b,000001,平安银行,SZSE,MAIN,2025-03-04,11,21,能,亏,-1,-1,能,亏,-2,-2,能,赚,3,3
c,600000,浦发银行,SSE,MAIN,2025-06-01,8,10,否,,,否,,,否,,
"""


class CloudStairStockHistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        path = Path(self.tmp.name) / "signals.csv"
        path.write_text(CSV, encoding="utf-8")
        self._orig = history.CANDIDATE_PATHS
        history.CANDIDATE_PATHS = (path,)
        history._index.cache_clear()

    def tearDown(self):
        history.CANDIDATE_PATHS = self._orig
        history._index.cache_clear()
        self.tmp.cleanup()

    def test_counts_and_win_rate_for_one_stock(self):
        row = history.stock_history("000001")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row["appear_count"], 2)
        self.assertEqual(row["first_date"], "2024-01-02")
        self.assertEqual(row["last_date"], "2025-03-04")
        self.assertEqual(row["t5"]["settled"], 2)
        self.assertEqual(row["t5"]["wins"], 1)
        self.assertEqual(row["t5"]["win_rate"], 50.0)
        self.assertEqual(row["recent_dates"], ["2025-03-04", "2024-01-02"])

    def test_missing_stock_is_none(self):
        self.assertIsNone(history.stock_history("999999"))


if __name__ == "__main__":
    unittest.main()
