"""参考数据刷新：新浪成分兜底与 staging 继承。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from utils import stock_info


class ReferenceMetadataFallbackTest(unittest.TestCase):
    def test_sina_industry_uses_sector_detail_not_spot_leaders_only(self):
        spot = pd.DataFrame(
            {
                "label": ["new_yh", "new_bj"],
                "板块": ["银行", "白酒"],
                "股票代码": ["sh600000", "sz000858"],
            }
        )
        bank = pd.DataFrame({"code": ["600000", "601398"]})
        liquor = pd.DataFrame({"code": ["000858", "600519"]})

        with (
            patch("akshare.stock_sector_spot", return_value=spot),
            patch(
                "akshare.stock_sector_detail",
                side_effect=[bank, liquor],
            ),
        ):
            mapping = stock_info._fetch_industry_mapping_sina()

        self.assertEqual(
            mapping,
            {
                "600000": "银行",
                "601398": "银行",
                "000858": "白酒",
                "600519": "白酒",
            },
        )

    def test_refresh_inherits_staging_reference_when_live_sources_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codes = [f"{600000 + i:06d}" for i in range(3000)]
            industries = {code: "银行" for code in codes}
            caps = {code: {"total_mv": 1e10, "circ_mv": 1e10} for code in codes}
            (root / "stock_industry.json").write_text(
                json.dumps({**industries, "_updated_at": "2026-08-04T16:00:00"}),
                encoding="utf-8",
            )
            (root / "stock_market_cap.json").write_text(
                json.dumps({**caps, "_updated_at": "2026-08-04T16:00:00"}),
                encoding="utf-8",
            )

            with (
                patch.object(
                    stock_info,
                    "fetch_industry_mapping",
                    return_value={"600000": "银行"},
                ),
                patch.object(
                    stock_info,
                    "fetch_market_caps",
                    return_value={"600000": {"total_mv": 1.0, "circ_mv": 1.0}},
                ),
            ):
                manifest = stock_info.refresh_reference_metadata(
                    root,
                    codes,
                    "2026-08-05",
                )

            self.assertTrue(manifest["valid"])
            self.assertEqual(
                manifest["industry"]["source_id"],
                "inherited-staging-snapshot",
            )
            self.assertEqual(manifest["industry"]["count"], 3000)
            self.assertEqual(manifest["market_cap"]["count"], 3000)
            restored = json.loads(
                (root / "stock_industry.json").read_text(encoding="utf-8")
            )
            self.assertEqual(restored["600000"], "银行")
            self.assertGreaterEqual(len(restored) - 1, 3000)


if __name__ == "__main__":
    unittest.main()
