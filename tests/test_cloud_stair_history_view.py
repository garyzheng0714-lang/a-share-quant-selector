import unittest

from utils.cloud_stair_history_view import history_signals, history_summary


class CloudStairHistoryViewTest(unittest.TestCase):
    def test_sealed_archive_summary_and_paging(self):
        summary = history_summary()
        self.assertTrue(summary["available"])
        self.assertEqual(summary["cutoff"], "2026-08-14")
        self.assertEqual(summary["signal_count"], 33342)
        self.assertEqual(summary["stock_count"], 4311)
        self.assertEqual(summary["today_count"], 22)
        self.assertAlmostEqual(summary["t1"]["win_rate"], 0.4388416610604856)
        self.assertIn("mean_net_return_pct", summary["t5"])
        self.assertIn("mean_net_return_pct", summary["t20"])
        first = history_signals(page=1, page_size=20)
        self.assertEqual(len(first["rows"]), 20)
        self.assertGreaterEqual(first["total"], first["page_size"])
        day = history_signals(date="2026-08-14", page=1, page_size=50)
        self.assertEqual(day["total"], 22)
        self.assertTrue(all(row["signal_date"] == "2026-08-14" for row in day["rows"]))
        search = history_signals(query="002612", page=1, page_size=20)
        self.assertTrue(any(row["code"] == "002612" for row in search["rows"]))


if __name__ == "__main__":
    unittest.main()
