import tempfile
import unittest
from pathlib import Path

from utils.csv_manager import CSVManager


class CsvManagerTest(unittest.TestCase):
    def test_training_csv_is_not_treated_as_stock(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "600000.csv").write_text("date,close\n2026-07-14,10\n")
            Path(tmp, "hierarchical_training.csv").write_text("date,target\n2026-07-14,1\n")
            self.assertEqual(CSVManager(tmp).list_all_stocks(), ["600000"])


if __name__ == "__main__":
    unittest.main()
