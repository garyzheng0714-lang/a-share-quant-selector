import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from utils.akshare_fetcher import AKShareFetcher
from utils.data_contracts import FetchResult, MarketDataUnavailable


def history(end: str, rows: int = 20) -> pd.DataFrame:
    dates = pd.date_range(end=end, periods=rows, freq="B")
    return pd.DataFrame(
        {
            "date": dates,
            "open": 10.0,
            "high": 11.0,
            "low": 9.0,
            "close": 10.0,
            "volume": 100,
            "amount": 1000,
            "turnover": 1.0,
            "market_cap": 1_000_000,
        }
    )


class MarketDataContractTest(unittest.TestCase):
    def test_all_history_sources_failed_returns_explicit_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            with (
                patch.object(fetcher, "_fetch_stock_history_http", return_value=None),
                patch(
                    "utils.akshare_fetcher.ak.stock_zh_a_hist", side_effect=TimeoutError
                ),
            ):
                result = fetcher.fetch_stock_history("600000", years=1)

        self.assertFalse(result.success)
        self.assertEqual(result.reason, "all_sources_failed")
        self.assertEqual(result.rows, 0)
        self.assertFalse(result.synthetic)
        self.assertTrue(result.data.empty)
        self.assertFalse(hasattr(AKShareFetcher, "_generate_mock_data"))

    def test_http_html_and_akshare_timeout_never_become_market_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            response = MagicMock()
            response.json.side_effect = ValueError("HTML is not JSON")
            with (
                patch("requests.get", return_value=response),
                patch(
                    "utils.akshare_fetcher.ak.stock_zh_a_hist",
                    side_effect=TimeoutError,
                ),
            ):
                result = fetcher.fetch_stock_history("600000", years=1)

            self.assertFalse(result.success)
            self.assertTrue(result.data.empty)
            self.assertEqual(result.reason, "all_sources_failed")
            self.assertEqual(fetcher.csv_manager.list_all_stocks(), [])

    def test_changed_http_json_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            response = MagicMock()
            response.json.return_value = ["unexpected", "schema"]
            with (
                patch("requests.get", return_value=response),
                patch(
                    "utils.akshare_fetcher.ak.stock_zh_a_hist",
                    side_effect=TimeoutError,
                ),
            ):
                result = fetcher.fetch_stock_history("600000", years=1)

            self.assertFalse(result.success)
            self.assertTrue(result.data.empty)

    @patch(
        "utils.data_freshness.expected_completed_trade_date", return_value="2026-07-14"
    )
    def test_failed_bootstrap_does_not_modify_existing_csv(self, _cutoff):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            fetcher._main_board_universe = lambda: {"600000": "浦发银行"}
            fetcher.csv_manager.write_stock("600000", history("2026-07-14", rows=20))
            path = fetcher.csv_manager.get_stock_path("600000")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            fetcher.fetch_stock_history = lambda code, years: FetchResult.failure(
                source="test",
                reason="all_sources_failed",
            )

            result = fetcher.bootstrap_universe()
            after = hashlib.sha256(path.read_bytes()).hexdigest()

        self.assertEqual(result["failed"], 1)
        self.assertEqual(before, after)

    @patch(
        "utils.data_freshness.expected_completed_trade_date", return_value="2026-07-14"
    )
    def test_stale_update_response_is_not_persisted(self, _cutoff):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            fetcher._main_board_universe = lambda: {"600000": "浦发银行"}
            original = history("2026-07-12", rows=20)
            fetcher.csv_manager.write_stock("600000", original)
            path = fetcher.csv_manager.get_stock_path("600000")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            fetcher.fetch_stock_update = lambda code, days: FetchResult.ok(
                history("2026-07-13", rows=2),
                source="test",
            )

            result = fetcher.daily_update()
            after = hashlib.sha256(path.read_bytes()).hexdigest()

        self.assertEqual(result["failed"], 1)
        self.assertEqual(
            result["stocks"][0]["error_code"], "returned_latest_date_mismatch"
        )
        self.assertEqual(before, after)

    @patch(
        "utils.data_freshness.expected_completed_trade_date",
        return_value="2026-07-14",
    )
    def test_daily_update_retries_a_transient_stock_failure(self, _cutoff):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            fetcher._main_board_universe = lambda: {"600000": "浦发银行"}
            fetcher.csv_manager.write_stock("600000", history("2026-07-13", rows=20))
            fetcher.fetch_stock_update = MagicMock(
                side_effect=[
                    FetchResult.failure(source="test", reason="source_failed"),
                    FetchResult.ok(history("2026-07-14", rows=2), source="test"),
                ]
            )

            result = fetcher.daily_update()

            self.assertEqual(result["failed"], 0)
            self.assertEqual(fetcher.fetch_stock_update.call_count, 2)
            latest = fetcher.csv_manager.read_stock("600000", nrows=1)
            self.assertEqual(str(latest.iloc[0]["date"])[:10], "2026-07-14")

    @patch("utils.akshare_fetcher.time.sleep", return_value=None)
    def test_partial_or_missing_universe_never_becomes_success(self, _sleep):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            with (
                patch.object(
                    fetcher,
                    "_fetch_stock_list_http",
                    return_value={"600000": "浦发银行"},
                ),
                patch(
                    "utils.akshare_fetcher.ak.stock_sh_a_spot_em",
                    side_effect=TimeoutError,
                ),
            ):
                with self.assertRaises(MarketDataUnavailable):
                    fetcher.get_all_stock_codes(max_retries=1)
            self.assertFalse((Path(tmp) / "stock_names.json").exists())

    def test_live_http_universe_fetch_never_returns_local_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            cached = {f"{600000 + index:06d}": f"股票{index}" for index in range(5000)}
            fetcher._save_stock_names(cached, source="akshare")
            no_codes = range(0)

            with patch("builtins.range", return_value=no_codes):
                result = fetcher._fetch_stock_list_http()

            self.assertEqual(result, {})
            self.assertEqual(fetcher._load_local_stock_names(), cached)

    def test_persisted_provenance_uses_actual_file_end_not_provider_future_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            provider_frame = history("2026-07-15", rows=3)
            fetch = FetchResult.ok(provider_frame, source="akshare")
            persisted = provider_frame[
                pd.to_datetime(provider_frame["date"]).dt.strftime("%Y-%m-%d")
                <= "2026-07-14"
            ].copy()

            fetcher._record_fetch_provenance(
                "600000", fetch, persisted, full_history=True
            )

            item = json.loads(
                (Path(tmp) / "ingestion_provenance.json").read_text(encoding="utf-8")
            )["stocks"]["600000"]
            self.assertEqual(item["source_trade_date"], "2026-07-14")
            self.assertEqual(item["persisted_end"], "2026-07-14")
            self.assertEqual(item["provider_returned_latest_date"], "2026-07-15")

    def test_last_known_good_universe_is_explicitly_marked_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            previous = {f"60{index:04d}": f"股票{index}" for index in range(3000)}
            fetcher._save_stock_names(previous, source="akshare")
            with patch(
                "utils.akshare_fetcher.ak.stock_sh_a_spot_em",
                side_effect=TimeoutError,
            ):
                result = fetcher.refresh_stock_universe()

            manifest = json.loads(
                (Path(tmp) / "universe_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(result, previous)
            self.assertFalse(fetcher.universe_refresh_status["fresh"])
            self.assertTrue(manifest["stale"])
            self.assertIn("live_universe_source_failed", manifest["last_refresh_error"])

    @patch.dict("os.environ", {"QUANT_MAX_UNIVERSE_DROP_RATIO": "0.10"})
    def test_abnormal_universe_shrink_keeps_lkg_and_blocks_fresh_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            previous = {
                f"{600000 + index:06d}": f"股票{index}" for index in range(4000)
            }
            fetcher._save_stock_names(previous, source="akshare")
            rows = pd.DataFrame(
                {
                    "代码": list(previous)[:3200],
                    "名称": list(previous.values())[:3200],
                    "最新价": 10.0,
                    "昨收": 9.8,
                }
            )
            with (
                patch(
                    "utils.akshare_fetcher.ak.stock_sh_a_spot_em",
                    return_value=rows.iloc[:1600],
                ),
                patch(
                    "utils.akshare_fetcher.ak.stock_sz_a_spot_em",
                    return_value=rows.iloc[1600:],
                ),
            ):
                result = fetcher.refresh_stock_universe()

            self.assertEqual(len(result), 4000)
            self.assertEqual(
                fetcher.universe_refresh_status["reason"],
                "universe_shrink_exceeded",
            )

    def test_universe_refresh_records_exact_date_suspensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            codes = [f"{600000 + index:06d}" for index in range(3000)]
            rows = pd.DataFrame(
                {
                    "代码": codes,
                    "名称": [f"股票{i}" for i in range(3000)],
                    "最新价": 10.0,
                    "昨收": 9.8,
                }
            )
            suspensions = pd.DataFrame(
                {
                    "代码": [codes[0]],
                    "停牌原因": ["临时停牌"],
                    "预计复牌时间": ["2026-07-16"],
                }
            )
            with (
                patch(
                    "utils.akshare_fetcher.ak.stock_sh_a_spot_em",
                    return_value=rows.iloc[:1500],
                ),
                patch(
                    "utils.akshare_fetcher.ak.stock_sz_a_spot_em",
                    return_value=rows.iloc[1500:],
                ),
                patch(
                    "utils.akshare_fetcher.ak.stock_tfp_em",
                    return_value=suspensions,
                ) as suspension_source,
                patch.object(
                    fetcher,
                    "_exchange_delisted_codes",
                    return_value=(
                        set(),
                        {
                            "schema_version": "exchange-delisted-catalog-v1",
                            "reason": "exchange_delisted",
                            "count": 0,
                            "content_hash": hashlib.sha256(b"[]").hexdigest(),
                            "sources": {},
                        },
                    ),
                ),
            ):
                result = fetcher.refresh_stock_universe("2026-07-15")

            status = json.loads(
                (Path(tmp) / "security_status.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(result), 3000)
            self.assertEqual(status["as_of"], "2026-07-15")
            self.assertEqual(status["suspended_count"], 1)
            self.assertEqual(status["securities"][codes[0]]["status"], "suspended")
            suspension_source.assert_called_once_with(date="20260715")

    def test_live_universe_excludes_non_active_securities_with_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            codes = [f"{600000 + index:06d}" for index in range(3003)]
            names = [f"股票{i}" for i in range(3003)]
            names[2] = "上药转换"
            rows = pd.DataFrame(
                {
                    "代码": codes,
                    "名称": names,
                    "最新价": 10.0,
                    "昨收": 9.8,
                }
            )
            rows.loc[1, ["最新价", "昨收"]] = float("nan")
            evidence = {
                "schema_version": "exchange-delisted-catalog-v1",
                "reason": "exchange_delisted",
                "count": 1,
                "content_hash": hashlib.sha256(
                    json.dumps([codes[0]], separators=(",", ":")).encode()
                ).hexdigest(),
                "sources": {"akshare:stock_info_sh_delist": {"count": 1}},
            }
            with (
                patch(
                    "utils.akshare_fetcher.ak.stock_sh_a_spot_em",
                    return_value=rows.iloc[:1500],
                ),
                patch(
                    "utils.akshare_fetcher.ak.stock_sz_a_spot_em",
                    return_value=rows.iloc[1500:],
                ),
                patch.object(
                    fetcher,
                    "_exchange_delisted_codes",
                    return_value=({codes[0]}, evidence),
                ),
                patch(
                    "utils.akshare_fetcher.ak.stock_tfp_em",
                    return_value=pd.DataFrame(columns=["代码"]),
                ),
            ):
                result = fetcher.refresh_stock_universe("2026-07-15")

            manifest = json.loads(
                (Path(tmp) / "universe_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(result), 3000)
            self.assertNotIn(codes[0], result)
            self.assertNotIn(codes[1], result)
            self.assertNotIn(codes[2], result)
            exclusions = manifest["exclusions"]
            self.assertEqual(exclusions["count"], 3)
            self.assertEqual(
                exclusions["categories"]["exchange_delisted"]["catalog"], evidence
            )
            self.assertEqual(exclusions["categories"]["not_yet_traded"]["count"], 1)
            self.assertEqual(exclusions["categories"]["non_equity_special"]["count"], 1)

    def test_exchange_delisted_sources_are_combined_with_auditable_hash(self):
        sh_codes = [f"{600000 + index:06d}" for index in range(60)]
        sz_codes = [f"{index:06d}" for index in range(50)]
        with (
            patch(
                "utils.akshare_fetcher.ak.stock_info_sh_delist",
                return_value=pd.DataFrame({"公司代码": sh_codes}),
            ),
            patch(
                "utils.akshare_fetcher.ak.stock_info_sz_delist",
                return_value=pd.DataFrame({"证券代码": sz_codes}),
            ),
        ):
            codes, evidence = AKShareFetcher._exchange_delisted_codes()

        expected = set(sh_codes + sz_codes)
        expected_hash = hashlib.sha256(
            json.dumps(sorted(expected), separators=(",", ":")).encode()
        ).hexdigest()
        self.assertEqual(codes, expected)
        self.assertEqual(evidence["count"], 110)
        self.assertEqual(evidence["content_hash"], expected_hash)

    def test_akshare_anchor_establishes_independent_history_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            initial = history("2026-07-14")
            fetcher.csv_manager.write_stock("600519", initial)
            fetcher._record_fetch_provenance(
                "600519",
                FetchResult.ok(initial, source="tencent"),
                initial,
                full_history=True,
            )
            fetcher._main_board_universe = lambda: {"600519": "贵州茅台"}
            with patch.object(
                fetcher,
                "_fetch_stock_history_akshare",
                return_value=FetchResult.ok(history("2026-07-14"), source="akshare"),
            ) as source:
                result = fetcher.ensure_akshare_history_anchor("2026-07-14")

            provenance = json.loads(
                (Path(tmp) / "ingestion_provenance.json").read_text(encoding="utf-8")
            )["stocks"]["600519"]
            self.assertTrue(result["success"])
            self.assertTrue(result["updated"])
            self.assertEqual(provenance["source_id"], "akshare")
            self.assertEqual(provenance["history_source_id"], "akshare")
            source.assert_called_once_with("600519", years=6)

    def test_empty_suspension_response_without_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)

            with self.assertRaisesRegex(ValueError, "suspension_schema_missing_code"):
                fetcher._save_security_status(
                    {"600000": "浦发银行"},
                    pd.DataFrame(),
                    "2026-07-15",
                )

            self.assertFalse((Path(tmp) / "security_status.json").exists())

    def test_lkg_universe_survives_eastmoney_suspension_outage(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            previous = {
                f"{600000 + index:06d}": f"股票{index}" for index in range(3200)
            }
            fetcher._save_stock_names(previous, source="akshare")
            confirmed = list(previous)[:3136]  # 98% of 3200

            with (
                patch(
                    "utils.akshare_fetcher.ak.stock_sh_a_spot_em",
                    side_effect=ConnectionError("eastmoney blocked"),
                ),
                patch(
                    "utils.akshare_fetcher.ak.stock_tfp_em",
                    side_effect=ConnectionError("eastmoney blocked"),
                ),
                patch.object(
                    fetcher,
                    "_confirm_cached_universe_tencent",
                    return_value={
                        "schema_version": "universe-verification-v1",
                        "source_id": "tencent:qt.gtimg.cn",
                        "confirmed_count": len(confirmed),
                        "confirmed_codes": confirmed,
                        "coverage_ratio": len(confirmed) / len(previous),
                        "failed_batches": 0,
                        "verified_at": "2026-07-15T16:00:00+08:00",
                    },
                ),
            ):
                result = fetcher.refresh_stock_universe("2026-07-15")

            status = json.loads(
                (Path(tmp) / "security_status.json").read_text(encoding="utf-8")
            )
            manifest = json.loads(
                (Path(tmp) / "universe_manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(result), 3136)
            self.assertTrue(fetcher.universe_refresh_status["fresh"])
            self.assertEqual(
                fetcher.universe_refresh_status["source"],
                "tencent-confirmed-last-known-good",
            )
            self.assertEqual(status["source_id"], "tencent:qt.gtimg.cn")
            self.assertEqual(status["as_of"], "2026-07-15")
            self.assertEqual(status["suspended_count"], 0)
            self.assertEqual(status["count"], 3136)
            self.assertNotIn("confirmed_codes", manifest.get("verification") or {})

    @patch(
        "utils.data_freshness.expected_completed_trade_date",
        return_value="2026-07-14",
    )
    def test_daily_update_accepts_only_verified_suspension_as_legal_stale(
        self, _cutoff
    ):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher = AKShareFetcher(tmp)
            fetcher._main_board_universe = lambda: {"600000": "浦发银行"}
            fetcher.csv_manager.write_stock("600000", history("2026-07-13", rows=20))
            fetcher._save_security_status(
                {"600000": "浦发银行"},
                pd.DataFrame({"代码": ["600000"], "停牌原因": ["临时停牌"]}),
                "2026-07-14",
            )
            fetcher.fetch_stock_update = MagicMock()

            result = fetcher.daily_update()

            self.assertEqual(result["failed"], 0)
            self.assertEqual(result["classified_non_trading"], 1)
            fetcher.fetch_stock_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
