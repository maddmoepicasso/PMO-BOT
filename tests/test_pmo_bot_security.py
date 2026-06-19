from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path


PMO_DIR = Path(__file__).resolve().parents[1]
PMO_BOT_PATH = PMO_DIR / "pmo_bot.py"


def load_pmo_bot():
    spec = importlib.util.spec_from_file_location("pmo_bot_under_test", PMO_BOT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_local_module(module_name):
    spec = importlib.util.spec_from_file_location(module_name, PMO_DIR / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class PMOBotSecuritySmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_pmo_bot()
        cls.client = cls.mod.app.test_client()

    def test_admin_token_is_configured_and_validated(self):
        token = self.mod.first_env("PMO_BOT_ADMIN_TOKEN")
        self.assertTrue(token)
        self.assertTrue(self.mod.pmo_admin_token_valid(token))
        self.assertFalse(self.mod.pmo_admin_token_valid("definitely-wrong-token"))

    def test_owner_post_route_requires_admin_token(self):
        response = self.client.post("/api/discord/test", json={})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.get_json()["locked"])

    def test_owner_post_route_accepts_admin_header(self):
        token = self.mod.first_env("PMO_BOT_ADMIN_TOKEN")
        response = self.client.post(
            "/api/tradingview/refresh-pine",
            json={},
            headers={"X-PMO-BOT-ADMIN-TOKEN": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])

    def test_data_collection_routes_require_admin_and_fail_closed(self):
        locked = self.client.post("/api/data-collection/enable", json={"timeout_minutes": 15, "max_trades": 5})
        self.assertEqual(locked.status_code, 403)
        self.assertTrue(locked.get_json()["locked"])

        status = self.client.get("/api/data-collection/status")
        self.assertEqual(status.status_code, 200)
        body = status.get_json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["data_collection"]["active"])
        self.assertFalse(body["live_unlocked"])
        self.assertFalse(body["orders_placed"])

    def test_data_collection_overlay_relaxes_paper_gates_only(self):
        token = self.mod.first_env("PMO_BOT_ADMIN_TOKEN")
        try:
            response = self.client.post(
                "/api/data-collection/enable",
                json={"timeout_minutes": 15, "max_trades": 5},
                headers={"X-Admin-Token": token},
            )
            self.assertEqual(response.status_code, 200)
            enabled = response.get_json()
            self.assertTrue(enabled["ok"])
            self.assertTrue(enabled["status"]["active"])

            effective = self.mod.pmo_data_collection_effective_settings(dict(self.mod.DEFAULT_SETTINGS))
            self.assertTrue(effective["DATA_COLLECTION_ACTIVE"])
            self.assertEqual(effective["PMO_REBUILD_ENTRY_SCORE_MIN"], 40.0)
            self.assertEqual(effective["PMO_REBUILD_ENTRY_SCORE_MAX"], 100.0)
            self.assertEqual(effective["PMO_WHY_NOT_MIN_RVOL"], 0.0)
            self.assertFalse(effective["PMO_WHY_NOT_REQUIRE_RVOL"])
            self.assertEqual(effective["PMO_OPENING_EARLIEST_ENTRY"], "09:30")
            self.assertEqual(effective["PMO_ORDER_NOTIONAL_USD"], 40.0)
            self.assertEqual(effective["PMO_MAX_ORDER_NOTIONAL_USD"], 40.0)
            self.assertIn("GAP_UP", effective["PMO_OPENING_ALLOWED_GAP_SIGNALS"])
            self.assertIn("GAP_DOWN", effective["PMO_OPENING_ALLOWED_GAP_SIGNALS"])
            self.assertIn("MIXED", effective["PMO_REGIME_LONG_ALLOWED_VALUES"])
            self.assertIn("DEFENSIVE", effective["PMO_REGIME_LONG_ALLOWED_VALUES"])
            self.assertEqual(effective["PMO_PAPER_MAX_DAILY_TRADES"], 100)
            self.assertTrue(effective["ALPACA_PAPER"])
            self.assertFalse(effective["PMO_ALLOW_LIVE_TRADING"])
            self.assertFalse(effective["PMO_LIVE_TRADING_ENABLED"])

            gap_down = self.mod.pmo_opening_hour_quality_gate(
                "NVDA",
                "LONG",
                "CALL_BIAS",
                {
                    "symbol": "NVDA",
                    "timestamp": "2026-06-17T09:36:00-04:00",
                    "edge_engines": {
                        "edge_engine_status": "READY",
                        "gap_signal": "GAP_DOWN",
                        "orb_signal": "BEARISH",
                    },
                },
                effective,
                rvol=1.5,
            )
            self.assertTrue(gap_down["allowed"])
            self.assertIn("data collection gap gate passed", " | ".join(gap_down["confirmations"]))

            fields = self.mod.pmo_data_collection_journal_fields("NVDA")
            self.assertTrue(fields["data_collection_mode"])
            self.assertIn("DATA_COLLECTION_", fields["data_collection_tag"])
        finally:
            self.client.post(
                "/api/data-collection/disable",
                json={},
                headers={"X-Admin-Token": token},
            )

        normal = self.mod.pmo_data_collection_effective_settings(dict(self.mod.DEFAULT_SETTINGS))
        self.assertFalse(normal["DATA_COLLECTION_ACTIVE"])
        self.assertEqual(normal["PMO_REBUILD_ENTRY_SCORE_MIN"], self.mod.DEFAULT_SETTINGS["PMO_REBUILD_ENTRY_SCORE_MIN"])

    def test_data_collection_accepts_200_trade_target(self):
        token = self.mod.first_env("PMO_BOT_ADMIN_TOKEN")
        try:
            response = self.client.post(
                "/api/data-collection/enable",
                json={"timeout_minutes": 10080, "max_trades": 200},
                headers={"X-Admin-Token": token},
            )
            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            self.assertTrue(body["ok"])
            self.assertTrue(body["status"]["active"])
            self.assertEqual(body["status"]["max_trades"], 200)
            self.assertEqual(body["status"]["target_trades"], 200)
            self.assertEqual(body["status"]["timeout_minutes"], 10080)
            self.assertIn("200 paper trades", body["message"])
        finally:
            self.client.post(
                "/api/data-collection/disable",
                json={},
                headers={"X-Admin-Token": token},
            )

    def test_data_collection_state_persists_across_manager_restart(self):
        module = load_local_module("pmo_data_collection_mode")
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "data_collection_state.json"
            manager = module.DataCollectionManager(state_file=state_file)
            enabled = manager.enable(timeout_minutes=10080, max_trades=200, enabled_by="test")
            self.assertTrue(enabled["status"]["active"])
            self.assertEqual(manager.record_trade("NVDA"), 1)

            restarted = module.DataCollectionManager(state_file=state_file)
            status = restarted.get_status()["data_collection"]
            self.assertTrue(status["active"])
            self.assertEqual(status["target_trades"], 200)
            self.assertEqual(status["trades_collected"], 1)
            self.assertEqual(status["trades_remaining"], 199)

    def test_voice_command_maps_data_collection_to_200_trade_target(self):
        parsed = self.mod.parse_ai_command("continue data collection until 200 trades", input_type="voice")
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["tool"], "enable_data_collection")
        self.assertEqual(parsed["arguments"]["max_trades"], 200)
        self.assertEqual(parsed["arguments"]["timeout_minutes"], 10080)

        legacy = self.mod.parse_ai_command("continue data collection until 150 trades", input_type="voice")
        self.assertTrue(legacy["ok"])
        self.assertEqual(legacy["tool"], "enable_data_collection")
        self.assertEqual(legacy["arguments"]["max_trades"], 200)

        status = self.mod.parse_ai_command("data collection status", input_type="voice")
        self.assertTrue(status["ok"])
        self.assertEqual(status["tool"], "get_data_collection_status")

    def test_clean_execution_doctrine_blocks_contaminated_normal_entries(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "DATA_COLLECTION_ACTIVE": False,
            "ENABLE_PMO_CLEAN_EXECUTION_DOCTRINE": True,
            "PMO_EXECUTION_DOCTRINE_REQUIRE_BULLISH": True,
            "PMO_EXECUTION_DOCTRINE_NORMAL_SCORE_MIN": 65,
            "PMO_EXECUTION_DOCTRINE_NORMAL_SCORE_MAX": 74.99,
        })

        blocked_symbol = self.mod.pmo_clean_execution_doctrine_gate(
            "HOOD",
            70,
            settings,
            mode="PAPER_ALPACA",
            market="STOCK",
            regime={"regime": "BULLISH"},
        )
        self.assertFalse(blocked_symbol["allowed"])
        self.assertIn("clean doctrine blocklist", " | ".join(blocked_symbol["blockers"]))

        high_score = self.mod.pmo_clean_execution_doctrine_gate(
            "SPY",
            90,
            settings,
            mode="PAPER_ALPACA",
            market="STOCK",
            regime={"regime": "BULLISH"},
        )
        self.assertFalse(high_score["allowed"])
        self.assertIn("clean doctrine score band", " | ".join(high_score["blockers"]))

        defensive = self.mod.pmo_clean_execution_doctrine_gate(
            "SPY",
            70,
            settings,
            mode="PAPER_ALPACA",
            market="STOCK",
            regime={"regime": "DEFENSIVE"},
        )
        self.assertFalse(defensive["allowed"])
        self.assertIn("clean doctrine regime gate", " | ".join(defensive["blockers"]))

    def test_clean_execution_doctrine_keeps_data_collection_isolated(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "DATA_COLLECTION_ACTIVE": True,
            "ENABLE_PMO_CLEAN_EXECUTION_DOCTRINE": True,
            "PMO_EXECUTION_DOCTRINE_REQUIRE_BULLISH": True,
            "PMO_EXECUTION_DOCTRINE_NORMAL_SCORE_MIN": 65,
            "PMO_EXECUTION_DOCTRINE_NORMAL_SCORE_MAX": 74.99,
        })

        result = self.mod.pmo_clean_execution_doctrine_gate(
            "SPY",
            90,
            settings,
            mode="PAPER_ALPACA",
            market="STOCK",
            regime={"regime": "DEFENSIVE"},
        )
        self.assertTrue(result["allowed"])
        self.assertEqual(result["status"], "DATA_COLLECTION_ISOLATED")
        self.assertTrue(result["data_collection_isolated"])
        self.assertIn("research-only", " | ".join(result["warnings"]))
        self.assertNotIn("clean doctrine score band", " | ".join(result["blockers"]))

    def test_ai_tool_manifest_includes_data_collection_tools(self):
        tools = {tool["name"]: tool for tool in self.mod.build_tool_manifest()}
        self.assertIn("get_data_collection_status", tools)
        self.assertEqual(tools["get_data_collection_status"]["permission"], "READ_ONLY")
        self.assertIn("enable_data_collection", tools)
        self.assertEqual(tools["enable_data_collection"]["permission"], "ADMIN_REQUIRED")

    def test_profit_tracker_snapshot_is_read_only(self):
        snapshot = self.mod.pmo_profit_tracker_snapshot(
            dict(self.mod.DEFAULT_SETTINGS),
            {
                "ok": True,
                "paper": True,
                "status": "ACTIVE",
                "equity": 1000,
                "last_equity": 990,
                "day_pnl": 10,
                "day_pnl_percent": 0.01,
                "buying_power": 1000,
            },
        )
        self.assertTrue(snapshot["ok"])
        self.assertEqual(snapshot["mode"], "READ_ONLY_PROFIT_TRACKER")
        self.assertFalse(snapshot["orders_placed"])
        self.assertFalse(snapshot["live_unlocked"])
        self.assertFalse(snapshot["money_movement"])
        self.assertIn("alpaca_gains", snapshot)
        self.assertIn("crypto_gains", snapshot)
        self.assertIn("net", snapshot)
        self.assertEqual(snapshot["summary"]["day_pnl"], 10)

    def test_profit_tracker_route_is_read_only(self):
        response = self.client.get("/api/profit-tracker")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["orders_placed"])
        self.assertFalse(payload["live_unlocked"])
        self.assertFalse(payload["money_movement"])

    def test_control_deck_uses_profit_tracker_not_payment_receiving_panel(self):
        response = self.client.get("/control")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("PMO Profit Tracker", html)
        self.assertIn("/api/profit-tracker", html)
        self.assertNotIn("Payment + Profit Receiving", html)
        self.assertNotIn("panelPaymentHub", html)

    def test_reports_route_blocks_env_and_source_files(self):
        blocked_paths = [
            self.mod.PMO_DIR / ".env",
            self.mod.PMO_DIR / "pmo_bot.py",
            self.mod.SETTINGS_FILE,
        ]
        for path in blocked_paths:
            with self.subTest(path=str(path)):
                response = self.client.get("/api/reports/open", query_string={"path": str(path)})
                self.assertEqual(response.status_code, 404)

    def test_reports_route_allows_approved_report_file(self):
        report = self.mod.REPORT_DIR / "pmo_test_smoke_report.txt"
        report.write_text("PMO smoke report OK\n", encoding="utf-8")
        try:
            response = self.client.get("/api/reports/open", query_string={"path": str(report)})
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"PMO smoke report OK", response.data)
            response.close()
        finally:
            report.unlink(missing_ok=True)

    def test_tradingview_rejects_missing_or_bad_secret(self):
        missing = self.client.post("/tradingview", json={"symbol": "SPY", "side": "LONG"})
        self.assertEqual(missing.status_code, 403)

        bad = self.client.post(
            "/tradingview",
            json={"secret": "wrong-secret", "symbol": "SPY", "side": "LONG"},
        )
        self.assertEqual(bad.status_code, 403)

    def test_tradingview_webhook_secret_prefers_env_value(self):
        original = os.environ.get("TRADINGVIEW_WEBHOOK_SECRET")
        try:
            os.environ["TRADINGVIEW_WEBHOOK_SECRET"] = "unit-test-webhook-secret"
            settings = self.mod.load_settings()
        finally:
            if original is None:
                os.environ.pop("TRADINGVIEW_WEBHOOK_SECRET", None)
            else:
                os.environ["TRADINGVIEW_WEBHOOK_SECRET"] = original
        self.assertEqual(settings["TRADINGVIEW_WEBHOOK_SECRET"], "unit-test-webhook-secret")

    def test_master_pine_source_does_not_embed_webhook_secret(self):
        source = self.mod.master_pine_source({"TRADINGVIEW_WEBHOOK_SECRET": "unit-test-webhook-secret"})
        self.assertIn("CHANGE_ME_SECRET", source)
        self.assertNotIn("unit-test-webhook-secret", source)

    def test_csv_append_mirrors_to_sqlite_event_log(self):
        csv_path = self.mod.CSV_DIR / "pmo_test_storage_events.csv"
        csv_path.unlink(missing_ok=True)
        row = {"event": "SMOKE_TEST", "status": "OK"}
        self.mod.csv_append(csv_path, row)
        try:
            self.assertTrue(csv_path.exists())
            self.assertTrue(self.mod.PMO_STORAGE_DB.exists())
            conn = sqlite3.connect(self.mod.PMO_STORAGE_DB)
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM pmo_event_log WHERE source_name = ? AND payload_json LIKE ?",
                    (csv_path.name, '%"SMOKE_TEST"%'),
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertGreaterEqual(count, 1)
        finally:
            csv_path.unlink(missing_ok=True)

    def test_agent_plan_is_admin_protected_and_review_only(self):
        locked = self.client.post("/api/agent/plan", json={"goal": "place a live trade"})
        self.assertEqual(locked.status_code, 403)

        token = self.mod.first_env("PMO_BOT_ADMIN_TOKEN")
        response = self.client.post(
            "/api/agent/plan",
            json={"goal": "place a live trade", "context": {"money_involved": True}},
            headers={"X-PMO-BOT-ADMIN-TOKEN": token},
        )
        self.assertEqual(response.status_code, 200)
        plan = response.get_json()["agent_plan"]
        self.assertFalse(plan["execution_allowed"])
        self.assertTrue(plan["owner_approval_required"])
        self.assertEqual(plan["mode"], "PLAN_REVIEW_ONLY")

    def test_claude_helper_fails_safe_without_key(self):
        original_first_env = self.mod.first_env
        try:
            self.mod.first_env = lambda *names: ""
            result = self.mod.pmo_claude_call("system", "user", expect_json=True)
            self.assertFalse(result["ok"])
            self.assertEqual(result["source"], "fallback")
            self.assertIn("ANTHROPIC_API_KEY", result["error"])
        finally:
            self.mod.first_env = original_first_env

    def test_ask_prompt_uses_xml_ground_truth_and_safety_contract(self):
        prompt = self.mod.pmo_ai_build_elite_system_prompt(dict(self.mod.DEFAULT_SETTINGS))
        self.assertIn("<role_constraints>", prompt)
        self.assertIn("<ground_truth>", prompt)
        self.assertIn("<output_contract>", prompt)
        self.assertIn("<live_pmo_state>", prompt)
        self.assertIn("Score inversion has been observed", prompt)
        self.assertIn("data_collection_target", prompt)
        self.assertIn("never_do", prompt)
        self.assertIn("place orders", prompt)
        self.assertIn("unlock live trading", prompt)

    def test_api_ask_sends_structured_prompt_without_unlocking_safety(self):
        original_first_env = self.mod.first_env
        original_call = self.mod.pmo_claude_call
        captured = {}
        try:
            self.mod.first_env = lambda *names: "test-key"

            def fake_call(system_prompt, user_prompt, *args, **kwargs):
                captured["system_prompt"] = system_prompt
                captured["user_prompt"] = user_prompt
                return {"ok": True, "text": "Decision: WAIT. Top factor: proof is still rebuilding.", "model": "test-model", "usage": {}}

            self.mod.pmo_claude_call = fake_call
            response = self.client.post("/api/ask", json={"question": "Should PMO take NVDA right now?"})
            self.assertEqual(response.status_code, 200)
            body = response.get_json()
            self.assertTrue(body["ok"])
            self.assertFalse(body["live_unlocked"])
            self.assertFalse(body["orders_placed"])
            self.assertFalse(body["settings_changed"])
            self.assertIn("<ground_truth>", captured["system_prompt"])
            self.assertIn("<live_pmo_state>", captured["system_prompt"])
            self.assertIn("<newest_user_message>", captured["user_prompt"])
            self.assertIn("<task>", captured["user_prompt"])
        finally:
            self.mod.first_env = original_first_env
            self.mod.pmo_claude_call = original_call

    def test_warp_ai_does_not_call_provider_on_passive_review(self):
        original_call = self.mod.pmo_claude_call
        calls = {"count": 0}
        try:
            def fake_call(*args, **kwargs):
                calls["count"] += 1
                return {"ok": True, "parsed": {"recommendation": "REVIEW", "confidence": 70, "risk_level": 40, "reason": "test"}}

            self.mod.pmo_claude_call = fake_call
            settings = dict(self.mod.DEFAULT_SETTINGS)
            settings.update({"PMO_AI_WARP_ENABLED": True, "PMO_WARP_AI_PROVIDER": "claude"})
            result = self.mod.pmo_warp_review(
                "PMO_BOT",
                "passive dashboard review",
                {"paper_mode": True, "dry_run": True},
                settings=settings,
                record=False,
            )
            self.assertEqual(calls["count"], 0)
            self.assertEqual(result["ai_provider"], "rule_based")
        finally:
            self.mod.pmo_claude_call = original_call

    def test_score_audit_post_requires_admin_token(self):
        response = self.client.post("/api/score/audit", json={"record": False})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.get_json()["locked"])

    def test_score_audit_fails_safe_without_anthropic_key(self):
        original_first_env = self.mod.first_env
        try:
            self.mod.first_env = lambda *names: ""
            result = self.mod.pmo_score_model_audit(dict(self.mod.DEFAULT_SETTINGS), record=False)
            self.assertFalse(result["ok"])
            self.assertIn("ANTHROPIC_API_KEY", result["error"])
        finally:
            self.mod.first_env = original_first_env

    def test_premarket_briefing_is_research_only_rule_based_by_default(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({"PMO_AI_BRIEFING_ENABLED": False, "PMO_WARP_AI_PROVIDER": "rule_based"})
        result = self.mod.pmo_generate_premarket_briefing(settings, record=False)
        self.assertTrue(result["ok"])
        self.assertTrue(result["research_only"])
        self.assertFalse(result["ai_generated"])
        self.assertEqual(result["ai_provider"], "rule_based")

    def test_calls_puts_readiness_uses_why_not_thresholds(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "ENABLE_PMO_SCORE_REBUILD_GATES": False,
            "PMO_WHY_NOT_MIN_SCORE": 75,
            "PMO_WHY_NOT_MIN_RVOL": 1.2,
            "PMO_WHY_NOT_REQUIRE_RVOL": True,
        })
        self.assertEqual(
            self.mod.calls_puts_readiness({"score": 74.9, "relative_volume": 2.0, "bias": "CALL_BIAS"}, settings),
            "WATCH",
        )
        self.assertEqual(
            self.mod.calls_puts_readiness({"score": 80, "relative_volume": 1.19, "bias": "CALL_BIAS"}, settings),
            "WATCH",
        )
        self.assertEqual(
            self.mod.calls_puts_readiness({"score": 75, "relative_volume": 1.2, "bias": "CALL_BIAS"}, settings),
            "CALL READY",
        )

    def test_trade_score_band_matches_current_ladder(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        cases = [
            (39, "IGNORE", "IGNORE", False, False, False),
            (40, "DISCOVERY", "DISCOVERY_WATCHLIST_ONLY", False, False, False),
            (54.9, "DISCOVERY", "DISCOVERY_WATCHLIST_ONLY", False, False, False),
            (55, "MONITOR", "MONITOR_ONLY", False, False, False),
            (64.9, "MONITOR", "MONITOR_ONLY", False, False, False),
            (65, "WATCH_ALERT", "WATCH_ALERT_ONLY", False, False, False),
            (77.9, "WATCH_ALERT", "WATCH_ALERT_ONLY", False, False, False),
            (78, "PAPER_SETUP", "PAPER_SETUP_CANDIDATE", True, False, False),
            (87.9, "PAPER_SETUP", "PAPER_SETUP_CANDIDATE", True, False, False),
            (88, "STRONG_PAPER", "STRONG_PAPER_CANDIDATE", True, True, False),
            (92.9, "STRONG_PAPER", "STRONG_PAPER_CANDIDATE", True, True, False),
            (93, "ELITE_PAPER", "ELITE_PAPER_EXTRA_CONFIRMATION", True, True, True),
        ]
        for score, band_name, action, paper_candidate, strong_candidate, elite_candidate in cases:
            with self.subTest(score=score):
                band = self.mod.pmo_trade_score_band(score, settings)
                self.assertEqual(band["band"], band_name)
                self.assertEqual(band["action"], action)
                self.assertEqual(band["paper_trade_candidate"], paper_candidate)
                self.assertEqual(band["strong_paper_candidate"], strong_candidate)
                self.assertEqual(band["elite_paper_candidate"], elite_candidate)

    def test_score_range_label_matches_executor_ladder(self):
        cases = [
            (39.9, "0-49 IGNORE"),
            (50, "50-64 DISCOVERY"),
            (65, "65-77 WATCH"),
            (78, "78-87 PAPER_CANDIDATE"),
            (88, "88-92 EXECUTOR"),
            (93, "93-100 ELITE"),
        ]
        for score, expected in cases:
            with self.subTest(score=score):
                self.assertEqual(self.mod.pmo_score_range_label(score, dict(self.mod.DEFAULT_SETTINGS)), expected)

    def test_international_quality_watchlist_tracks_core_top_and_otc_safety(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        snapshot = self.mod.pmo_international_quality_watchlist(settings)
        rows_by_symbol = {row["symbol"]: row for row in snapshot["rows"]}

        self.assertTrue(snapshot["ok"])
        self.assertTrue(snapshot["watchlist_only"])
        self.assertFalse(snapshot["live_order_unlocked"])
        self.assertEqual(snapshot["core_20_count"], 20)
        self.assertEqual(snapshot["higher_risk_count"], 5)
        self.assertEqual(snapshot["allocation_model_pct"]["AI_CHIPS"], 40)
        self.assertIn("TSM", snapshot["top_10"])
        self.assertIn("ADYEY", snapshot["top_10"])
        self.assertEqual(rows_by_symbol["TSM"]["execution_mode"], "US_LISTED_ADR_COMMON")
        self.assertEqual(rows_by_symbol["ADYEY"]["broker_support"], "VERIFY_OTC_SUPPORT")
        self.assertTrue(rows_by_symbol["ADYEY"]["top_10"])
        self.assertEqual(rows_by_symbol["BABA"]["tier"], "HIGHER_RISK")

    def test_international_quality_symbols_join_market_universe_when_enabled(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings["ENABLE_PMO_MICRO_ACCOUNT_MODE"] = False
        universe = self.mod.pmo_market_universe(settings)
        self.assertIn("ASML", universe)
        self.assertIn("NVO", universe)
        self.assertIn("OTGLY", universe)

        settings["ENABLE_PMO_INTERNATIONAL_QUALITY_WATCHLIST"] = False
        disabled_universe = self.mod.pmo_market_universe(settings)
        self.assertNotIn("ASML", disabled_universe)
        self.assertNotIn("OTGLY", disabled_universe)

    def test_international_quality_endpoint_is_read_only(self):
        response = self.client.get("/api/international-quality-watchlist")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["watchlist_only"])
        self.assertFalse(payload["live_order_unlocked"])
        self.assertFalse(payload["settings_changed_by_endpoint"])
        self.assertGreaterEqual(len(payload["rows"]), 20)

    def test_paper_proof_diagnosis_excludes_v112_replays_from_current_proof(self):
        original_trade_journal = self.mod.TRADE_JOURNAL_FILE
        original_v112_journal = self.mod.PMO_V112_REPLAY_JOURNAL_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.mod.TRADE_JOURNAL_FILE = Path(tmp) / "pmo_bot_trade_journal.csv"
                self.mod.PMO_V112_REPLAY_JOURNAL_FILE = Path(tmp) / "pmo_v112_paper_replay_journal.csv"
                self.mod.csv_append(self.mod.TRADE_JOURNAL_FILE, {
                    "timestamp": "2026-06-17T10:00:00-04:00",
                    "status": "CLOSED_WIN",
                    "symbol": "SPY",
                    "side": "LONG",
                    "entry_price": "100",
                    "exit_price": "104",
                    "pnl": "4",
                    "pnl_pct": "4",
                    "source_order_id": "broker-1",
                })
                self.mod.csv_append(self.mod.PMO_V112_REPLAY_JOURNAL_FILE, {
                    "timestamp": "2026-06-17T10:05:00-04:00",
                    "status": "TARGET_HIT",
                    "quality": "WIN",
                    "symbol": "QQQ",
                    "side": "BUY_LONG",
                    "entry_price": "200",
                    "exit_price": "210",
                    "profit_loss_usd": "10",
                    "profit_loss_pct": "5",
                    "executor_source_order_id": "replay-1",
                })
                self.mod.csv_append(self.mod.PMO_V112_REPLAY_JOURNAL_FILE, {
                    "timestamp": "2026-06-17T10:10:00-04:00",
                    "status": "STOP_HIT",
                    "quality": "LOSS",
                    "symbol": "IWM",
                    "side": "BUY_LONG",
                    "entry_price": "100",
                    "exit_price": "96",
                    "profit_loss_usd": "-4",
                    "profit_loss_pct": "-4",
                    "executor_source_order_id": "replay-2",
                })

                result = self.mod.pmo_paper_proof_diagnosis(dict(self.mod.DEFAULT_SETTINGS), record=False, limit=100)
                self.assertEqual(result["closed_outcomes"], 1)
                self.assertEqual(result["wins"], 1)
                self.assertEqual(result["losses"], 0)
                self.assertEqual(result["source_counts"]["closed_by_source"]["trade_journal"], 1)
                self.assertEqual(result["source_counts"]["v112_excluded_from_current_proof"], 2)
                self.assertTrue(result["v112_replay_exclusion"]["excluded_from_current_proof"])
                self.assertFalse(next(row for row in result["source_inventory"] if row["source"] == "v112_replay")["counts_as_closed_proof"])
        finally:
            self.mod.TRADE_JOURNAL_FILE = original_trade_journal
            self.mod.PMO_V112_REPLAY_JOURNAL_FILE = original_v112_journal

    def test_sqlite_paper_outcome_upsert_populates_legacy_created_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "pmo_storage.sqlite3"
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE paper_outcomes (
                        trade_id TEXT PRIMARY KEY,
                        created_at TEXT NOT NULL,
                        updated_at TEXT,
                        symbol TEXT,
                        result TEXT,
                        rules_followed INTEGER,
                        pnl_pct REAL,
                        payload_json TEXT
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

            self.mod.storage_sqlite_upsert_paper_outcome(
                db_path,
                {
                    "replay_id": "PMO-TEST-1",
                    "timestamp": "2026-06-12T09:30:00-04:00",
                    "symbol": "SPY",
                    "quality": "WIN",
                    "pnl_pct": "1.25",
                    "rules_followed": True,
                },
            )
            conn = sqlite3.connect(db_path)
            try:
                row = conn.execute(
                    "SELECT created_at, updated_at, symbol, result, rules_followed, pnl_pct FROM paper_outcomes WHERE trade_id = ?",
                    ("PMO-TEST-1",),
                ).fetchone()
            finally:
                conn.close()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "2026-06-12T09:30:00-04:00")
            self.assertTrue(row[1])
            self.assertEqual(row[2], "SPY")
            self.assertEqual(row[3], "WIN")
            self.assertEqual(row[4], 1)
            self.assertAlmostEqual(row[5], 1.25)

    def test_build_trade_plan_scales_notional_below_full_size_score(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "PMO_ORDER_NOTIONAL_USD": 60.0,
            "PMO_MAX_ORDER_NOTIONAL_USD": 60.0,
            "PMO_MAX_BUYING_POWER_USE_PER_ORDER": 1.0,
            "PMO_SMART_LIMIT_FULL_SIZE_SCORE": 88,
            "PMO_DEFAULT_STOP_LOSS_PCT": 4.0,
            "PMO_DEFAULT_TAKE_PROFIT_PCT": 6.0,
            "PMO_MIN_RISK_REWARD_RATIO": 1.4,
        })
        plan = self.mod.bot.build_trade_plan(
            {"symbol": "SPY", "side": "LONG", "score": 72, "market_data": {"price": 100}},
            {"entry_price": 100},
            account={"buying_power": 1000},
            record=False,
            settings_override=settings,
        )
        self.assertEqual(plan["notional_scale"], 0.818)
        self.assertAlmostEqual(plan["notional"], 49.08)
        self.assertAlmostEqual(plan["max_loss_usd"], 1.96)

    def test_crypto_profile_endpoint_returns_strategy_params(self):
        response = self.client.get(
            "/api/crypto/profile",
            query_string={"ticker": "SOL/USD", "entry_price": 65, "hour_et": 20},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["is_crypto"])
        self.assertTrue(data["is_proven"])
        self.assertEqual(data["ticker"], "SOL/USD")
        self.assertAlmostEqual(data["stop_pct"], 6.0)
        self.assertAlmostEqual(data["tp_pct"], 10.0)
        self.assertAlmostEqual(data["trail_act"], 5.0)
        self.assertAlmostEqual(data["trail_stop"], 3.0)
        self.assertEqual(data["max_hold"], 720)
        self.assertEqual(data["partial_exits"][0]["at_price"], 68.25)
        self.assertEqual(data["partial_exits"][1]["at_price"], 70.2)
        summary = self.client.get("/api/crypto/summary").get_json()
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["total_trades"], 15)
        self.assertEqual(summary["total_losses"], 0)

    def test_build_trade_plan_uses_crypto_profile_for_crypto_symbols(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "PMO_CRYPTO_PROFILE_ENABLED": True,
            "PMO_ORDER_NOTIONAL_USD": 40.0,
            "PMO_MAX_ORDER_NOTIONAL_USD": 60.0,
            "PMO_MAX_BUYING_POWER_USE_PER_ORDER": 1.0,
            "PMO_SMART_LIMIT_FULL_SIZE_SCORE": 88,
            "PMO_MIN_RISK_REWARD_RATIO": 1.5,
        })
        plan = self.mod.bot.build_trade_plan(
            {"symbol": "SOL/USD", "side": "LONG", "score": 88, "market_data": {"price": 65}},
            {"entry_price": 65},
            account={"buying_power": 1000},
            record=False,
            settings_override=settings,
        )
        self.assertEqual(plan["strategy_family"], "CRYPTO_PROFILE")
        self.assertAlmostEqual(plan["notional"], 50.0)
        self.assertAlmostEqual(plan["stop_loss_pct"], 6.0)
        self.assertAlmostEqual(plan["take_profit_pct"], 10.0)
        self.assertAlmostEqual(plan["trailing_activation_profit_pct"], 5.0)
        self.assertAlmostEqual(plan["trailing_stop_pct"], 3.0)
        self.assertEqual(plan["max_hold_minutes"], 720)
        self.assertEqual(plan["partial_exits"][0]["size_pct"], 40)
        self.assertEqual(plan["partial_exits"][1]["size_pct"], 30)

    def test_trade_truth_endpoint_returns_improvement_checklist(self):
        original_trade_journal = self.mod.TRADE_JOURNAL_FILE
        original_why_not_events = self.mod.PMO_WHY_NOT_EVENTS_FILE
        original_market_regime = self.mod.bot.market_regime
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.mod.TRADE_JOURNAL_FILE = Path(tmp) / "pmo_bot_trade_journal.csv"
                self.mod.PMO_WHY_NOT_EVENTS_FILE = Path(tmp) / "pmo_why_not_events.csv"
                self.mod.bot.market_regime = lambda: {"regime": "BULLISH", "reason": "test"}
                self.mod.csv_append(self.mod.TRADE_JOURNAL_FILE, {
                    "timestamp": "2026-06-12T09:30:00-04:00",
                    "status": "CLOSED_WIN",
                    "symbol": "SPY",
                    "side": "LONG",
                    "score": 88,
                    "pnl": 1.0,
                    "exit_price": 101.0,
                    "market": "STOCK",
                    "market_regime": "BULLISH",
                })
                response = self.client.get("/api/trade-truth")
                self.assertEqual(response.status_code, 200)
                payload = response.get_json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["engine"], "PMO Trade Truth Engine")
                self.assertEqual(len(payload["checklist"]), 10)
                self.assertIn("88-92 EXECUTOR", payload["checklist"][1]["bands"])
        finally:
            self.mod.TRADE_JOURNAL_FILE = original_trade_journal
            self.mod.PMO_WHY_NOT_EVENTS_FILE = original_why_not_events
            self.mod.bot.market_regime = original_market_regime

    def test_watchlist_refresh_updates_market_data_freshness_clock(self):
        bot = self.mod.bot
        original_settings = bot.settings
        original_get_latest_price = bot.get_latest_price
        original_market_universe = self.mod.pmo_market_universe
        original_crypto_symbols = self.mod.pmo_crypto_symbols
        try:
            bot.settings = dict(self.mod.DEFAULT_SETTINGS)
            bot.settings.update({
                "PMO_WATCHLIST": ["SPY"],
                "PMO_AUTO_WATCHLIST_UNIVERSE": [],
            })
            bot.market_data_status = {}
            bot.get_latest_price = lambda symbol, market="AUTO": {
                "ok": True,
                "symbol": symbol,
                "market": "STOCK",
                "price": 100,
                "feed": "TEST",
                "timestamp": "2026-06-12T09:30:00-04:00",
            }
            self.mod.pmo_market_universe = lambda settings: []
            self.mod.pmo_crypto_symbols = lambda settings, limit=40: []
            rows = bot.refresh_watchlist()
            self.assertGreaterEqual(len(rows), 1)
            self.assertTrue(bot.market_data_status.get("updated"))
            self.assertEqual(bot.market_data_status.get("watchlist_rows"), len(rows))
            self.assertEqual(bot.market_data_status.get("watchlist_ok"), len(rows))
        finally:
            bot.settings = original_settings
            bot.get_latest_price = original_get_latest_price
            self.mod.pmo_market_universe = original_market_universe
            self.mod.pmo_crypto_symbols = original_crypto_symbols

    def test_intraday_refresh_uses_configurable_symbol_cap(self):
        original_fetch = self.mod.pmo_fetch_intraday_bars
        original_load_auto = self.mod.load_auto_watchlist
        original_last_refresh = self.mod._intraday_last_refresh
        attempted = []
        try:
            self.mod._intraday_last_refresh = None
            self.mod.load_auto_watchlist = lambda: {"symbols": [], "selected": []}
            self.mod.pmo_fetch_intraday_bars = lambda symbol, lookback_bars=78, settings=None: attempted.append(symbol) or {
                "ok": True,
                "rows": 12,
            }
            settings = dict(self.mod.DEFAULT_SETTINGS)
            settings.update({
                "PMO_INTRADAY_REFRESH_ENABLED": True,
                "PMO_INTRADAY_REFRESH_MAX_SYMBOLS": 55,
                "PMO_WATCHLIST": [f"TST{i:03d}" for i in range(70)],
                "PMO_AUTO_WATCHLIST_UNIVERSE": [],
            })
            result = self.mod.pmo_refresh_intraday_watchlist(settings, force=True)
        finally:
            self.mod.pmo_fetch_intraday_bars = original_fetch
            self.mod.load_auto_watchlist = original_load_auto
            self.mod._intraday_last_refresh = original_last_refresh
        self.assertTrue(result["ok"])
        self.assertEqual(result["symbols_attempted"], 55)
        self.assertEqual(len(attempted), 55)

    def test_edge_library_defines_all_requested_edges(self):
        definitions = self.mod.pmo_edge_library_definitions()
        self.assertEqual(len(definitions), 16)
        ids = {row["id"] for row in definitions}
        self.assertIn("momentum_breakout", ids)
        self.assertIn("fair_value_gap", ids)
        self.assertIn("adaptive_sizing", ids)
        self.assertIn("option_flow_bias", ids)
        self.assertIn("latency_arb", ids)

    def test_edge_library_evaluates_data_backed_edges_without_order_permission(self):
        rows = []
        for index in range(60):
            close = 100 + index * 0.2
            rows.append({
                "date": f"2026-05-{(index % 28) + 1:02d}",
                "open": close - 0.5,
                "high": close + 0.5,
                "low": close - 1.0,
                "close": close,
                "volume": 1000,
            })
        rows[-1].update({"close": 125, "high": 126, "low": 121, "volume": 3000})
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "PMO_ORDER_NOTIONAL_USD": 40.0,
            "PMO_MAX_ORDER_NOTIONAL_USD": 60.0,
            "PMO_SMART_LIMIT_FULL_SIZE_SCORE": 88,
        })
        report = self.mod.pmo_evaluate_edge_library(
            settings,
            "SPY",
            latest={"ok": True, "symbol": "SPY", "price": 125},
            bars={"ok": True, "change_pct": 3.0, "relative_volume": 2.0},
            daily_rows=rows,
            intraday_rows=[],
            score=72,
            record=False,
        )
        self.assertTrue(report["ok"])
        self.assertFalse(report["live_order_allowed"])
        self.assertEqual(report["edge_count"], 16)
        by_id = {row["id"]: row for row in report["edges"]}
        self.assertEqual(by_id["momentum_breakout"]["status"], "READY")
        self.assertEqual(by_id["fair_value_gap"]["status"], "DATA_REQUIRED")
        self.assertEqual(by_id["order_flow_tape"]["status"], "DATA_REQUIRED")
        self.assertEqual(by_id["adaptive_sizing"]["status"], "SIZING_ONLY")
        self.assertEqual(by_id["adaptive_sizing"]["notional_scale"], 0.818)

    def test_edge_library_route_is_signal_only(self):
        response = self.client.get("/api/edges")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["live_order_allowed"])
        self.assertEqual(len(payload["definitions"]), 16)

    def test_edge_library_recording_requires_admin_token(self):
        response = self.client.post("/api/edges/evaluate", json={"symbol": "SPY", "record": True})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.get_json()["locked"])

    def test_advanced_edge_library_is_research_only(self):
        definitions = self.mod.pmo_advanced_microstructure_edge_definitions()
        self.assertEqual(len(definitions), 12)
        ids = {row["id"] for row in definitions}
        self.assertIn("queue_jump_detection", ids)
        self.assertIn("mev_aware_crypto_execution", ids)

        response = self.client.get("/api/edges/advanced")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["live_order_allowed"])
        self.assertFalse(payload["paper_order_allowed"])
        self.assertEqual(len(payload["definitions"]), 12)

    def test_cobr_signal_module_emits_signal_only_research_rows(self):
        cobr_signal = load_local_module("cobr_signal")
        cobr_signal.reset_state()
        now_ms = 100000
        books = {
            "TGT": [(100.0, 3, 3)] + [(100.0 + i * 0.01, 1, 1) for i in range(1, 8)],
            "CORR": [(100.0, 3, 3)] + [(100.0 + i * 0.01, 1, 1) for i in range(1, 8)],
        }
        trades = [
            {"symbol": "TGT", "price": 100.0, "size": 125, "side": "buy", "ts": now_ms},
            {"symbol": "TGT", "price": 100.0, "size": 125, "side": "buy", "ts": now_ms},
            {"symbol": "CORR", "price": 100.0, "size": 125, "side": "buy", "ts": now_ms},
        ]
        prices = {"TGT": [100.0, 99.95, 100.01, 99.98, 100.0], "CORR": [100.0, 100.01, 99.99, 100.02, 100.0]}
        signals = cobr_signal.cobr_on_tick("TGT", "CORR", books, trades, prices, now_ms=now_ms)
        self.assertGreaterEqual(len(signals), 1)
        self.assertTrue(all(signal.get("signal_only") for signal in signals))

    def test_market_simulator_runs_cobr_replay_and_pnl_demo(self):
        market_simulator = load_local_module("market_simulator")
        cobr_signal = load_local_module("cobr_signal")
        result = market_simulator.run_synthetic_cobr_replay(duration_ms=400, step_ms=20)
        self.assertTrue(result["ok"])
        self.assertFalse(result["live_order_allowed"])
        self.assertIn("signals", result)
        self.assertIn("fills", result)

        sim = market_simulator.MarketSimulator(starting_cash=100000.0)
        sim.ingest_trade({"ts": 1.0, "price": 100.0, "qty": 5.0, "side": "buy"})
        sim.ingest_trade({"ts": 2.0, "price": 100.5, "qty": 5.0, "side": "sell"})
        buy_id = sim.place_limit(side="buy", price=100.1, qty=5.0, ts=1.1, client_id="TEST")
        sell_id = sim.place_limit(side="sell", price=100.4, qty=5.0, ts=2.1, client_id="TEST")
        self.assertTrue(buy_id)
        self.assertTrue(sell_id)
        self.assertGreaterEqual(len(sim.list_fills()), 2)
        pnl = sim.get_pnl(mark_price=100.5)
        self.assertIn("total_equity", pnl)
        self.assertGreaterEqual(pnl["realized_pnl"], 0)
        self.assertTrue(hasattr(cobr_signal, "COBRSignal"))

    def test_cobr_simulation_recording_requires_admin_token(self):
        response = self.client.post("/api/cobr/simulate", json={"record": True, "duration_ms": 300})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.get_json()["locked"])

        status = self.client.get("/api/cobr/status")
        self.assertEqual(status.status_code, 200)
        payload = status.get_json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["live_order_allowed"])

    def test_vwap_why_not_blocks_directional_mismatch_only(self):
        original_loader = self.mod.pmo_edge_load_ohlcv_rows
        try:
            rows = [
                {"open": 100, "high": 100.2, "low": 99.8, "close": 100, "volume": 1000}
                for _ in range(30)
            ]
            self.mod.pmo_edge_load_ohlcv_rows = lambda symbol, intraday=False, limit=260: rows if intraday else []
            settings = dict(self.mod.DEFAULT_SETTINGS)
            settings.update({
                "ENABLE_PMO_WHY_NOT_VWAP_BLOCKER": True,
                "PMO_WHY_NOT_REQUIRE_VWAP_DATA": False,
                "PMO_WHY_NOT_VWAP_TOLERANCE_PCT": 0.15,
                "PMO_WHY_NOT_MIN_SCORE": 78,
                "PMO_WHY_NOT_MIN_RVOL": 1.5,
                "PMO_WHY_NOT_REQUIRE_RVOL": True,
            })
            result = self.mod.pmo_why_not_for_row(
                {"ok": True, "symbol": "SPY", "score": 90, "bias": "CALL_BIAS", "relative_volume": 2.0, "price": 98.0},
                settings,
                {"regime": "BULLISH", "risk_multiplier": 1.0},
                account={"ok": True, "equity": 200, "day_pnl": 0, "day_pnl_percent": 0},
                reconciliation={"status": "SYNCED"},
            )
            self.assertEqual(result["severity"], "BLOCKED")
            self.assertIn("VWAP blocker", " | ".join(result["blockers"]))
            self.assertEqual(result["vwap_check"]["status"], "BLOCK")
            self.assertLess(result["vwap_distance_pct"], -1.0)
        finally:
            self.mod.pmo_edge_load_ohlcv_rows = original_loader

    def test_vwap_why_not_pass_does_not_boost_weak_score(self):
        original_loader = self.mod.pmo_edge_load_ohlcv_rows
        try:
            rows = [
                {"open": 100, "high": 100.2, "low": 99.8, "close": 100, "volume": 1000}
                for _ in range(30)
            ]
            self.mod.pmo_edge_load_ohlcv_rows = lambda symbol, intraday=False, limit=260: rows if intraday else []
            settings = dict(self.mod.DEFAULT_SETTINGS)
            settings.update({
                "ENABLE_PMO_SCORE_REBUILD_GATES": False,
                "ENABLE_PMO_WHY_NOT_VWAP_BLOCKER": True,
                "PMO_WHY_NOT_MIN_SCORE": 78,
                "PMO_WHY_NOT_MIN_RVOL": 1.5,
                "PMO_WHY_NOT_REQUIRE_RVOL": True,
            })
            result = self.mod.pmo_why_not_for_row(
                {"ok": True, "symbol": "SPY", "score": 74, "bias": "CALL_BIAS", "relative_volume": 2.0, "price": 100.25},
                settings,
                {"regime": "BULLISH", "risk_multiplier": 1.0},
                account={"ok": True, "equity": 200, "day_pnl": 0, "day_pnl_percent": 0},
                reconciliation={"status": "SYNCED"},
            )
            self.assertEqual(result["vwap_check"]["status"], "PASS")
            self.assertIn("VWAP blocker pass", " | ".join(result["confirmations"]))
            self.assertEqual(result["severity"], "BLOCKED")
            self.assertIn("score 74 below PMO minimum 78", " | ".join(result["blockers"]))
        finally:
            self.mod.pmo_edge_load_ohlcv_rows = original_loader

    def test_vwap_why_not_stale_intraday_data_warns_instead_of_blocking_by_default(self):
        original_loader = self.mod.pmo_edge_load_ohlcv_rows
        try:
            rows = [
                {"date": "2000-01-01T15:55:00Z", "open": 100, "high": 100.2, "low": 99.8, "close": 100, "volume": 1000}
                for _ in range(30)
            ]
            self.mod.pmo_edge_load_ohlcv_rows = lambda symbol, intraday=False, limit=260: rows if intraday else []
            settings = dict(self.mod.DEFAULT_SETTINGS)
            settings.update({
                "ENABLE_PMO_WHY_NOT_VWAP_BLOCKER": True,
                "PMO_WHY_NOT_REQUIRE_VWAP_DATA": False,
                "PMO_WHY_NOT_VWAP_MAX_DATA_AGE_HOURS": 72,
            })
            result = self.mod.pmo_vwap_why_not_check(
                {"ok": True, "symbol": "SPY", "score": 90, "bias": "CALL_BIAS", "relative_volume": 2.0, "price": 80.0},
                settings,
            )
            self.assertEqual(result["status"], "DATA_REQUIRED")
            self.assertIn("stale", result["warning"])
            self.assertFalse(result["blocker"])
        finally:
            self.mod.pmo_edge_load_ohlcv_rows = original_loader

    def test_discovery_threshold_does_not_lower_trade_review_threshold(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "PMO_AUTO_WATCHLIST_MIN_SCORE": 40,
            "PMO_WHY_NOT_MIN_SCORE": 75,
            "PMO_WHY_NOT_MIN_RVOL": 1.2,
            "PMO_WHY_NOT_REQUIRE_RVOL": True,
        })
        band = self.mod.pmo_trade_score_band(56.5, settings)
        readiness = self.mod.calls_puts_readiness(
            {"score": 56.5, "relative_volume": 2.0, "bias": "CALL_BIAS"},
            settings,
        )
        self.assertEqual(band["band"], "MONITOR")
        self.assertTrue(band["discovery_candidate"])
        self.assertFalse(band["paper_trade_candidate"])
        self.assertEqual(readiness, "WAIT")

    def test_paper_proof_quality_breaker_blocks_bad_closed_outcomes(self):
        original_trade_journal = self.mod.TRADE_JOURNAL_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.mod.TRADE_JOURNAL_FILE = Path(tmp) / "pmo_bot_trade_journal.csv"
                for index in range(2):
                    self.mod.csv_append(self.mod.TRADE_JOURNAL_FILE, {
                        "timestamp": f"2026-06-11T10:00:{index:02d}",
                        "status": "CLOSED_WIN",
                        "symbol": f"WIN{index}",
                        "side": "LONG",
                        "pnl": 1.0,
                    })
                for index in range(25):
                    self.mod.csv_append(self.mod.TRADE_JOURNAL_FILE, {
                        "timestamp": f"2026-06-11T10:01:{index:02d}",
                        "status": "CLOSED_LOSS",
                        "symbol": f"LOSS{index}",
                        "side": "LONG",
                        "pnl": -1.0,
                    })
                settings = dict(self.mod.DEFAULT_SETTINGS)
                settings.update({
                    "ENABLE_PMO_PAPER_PROOF_QUALITY_BREAKER": True,
                    "PMO_CLOSED_TRADE_AUTHORITY": "REAL_TRADE_JOURNAL",
                    "PMO_PAPER_PROOF_BREAKER_MIN_CLOSED_TRADES": 20,
                    "PMO_PAPER_PROOF_BREAKER_MIN_WIN_RATE": 0.35,
                    "PMO_PAPER_PROOF_BREAKER_MIN_PROFIT_FACTOR": 0.80,
                })
                result = self.mod.pmo_paper_proof_quality_breaker(settings)
                self.assertTrue(result["active"])
                self.assertEqual(result["closed_trades"], 27)
                blockers = " | ".join(result["blockers"])
                self.assertIn("win rate", blockers)
                self.assertIn("profit factor", blockers)
        finally:
            self.mod.TRADE_JOURNAL_FILE = original_trade_journal

    def test_micro_drawdown_caution_blocks_new_entries_by_dollars(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update(self.mod.pmo_micro_account_mode_updates())
        original_lock = self.mod.PMO_DRAWDOWN_LOCK_FILE
        with tempfile.TemporaryDirectory() as tmp:
            self.mod.PMO_DRAWDOWN_LOCK_FILE = Path(tmp) / "drawdown_lock.json"
            try:
                result = self.mod.pmo_day_drawdown_governor(
                    settings,
                    {"ok": True, "equity": 200, "day_pnl": -1.6, "day_pnl_percent": -0.8},
                    symbol="SPY",
                    action="NEW_ENTRY",
                    record=False,
                )
            finally:
                self.mod.PMO_DRAWDOWN_LOCK_FILE = original_lock
        self.assertEqual(result["micro_stage"], "CAUTION")
        self.assertEqual(result["status"], "CAUTION")
        self.assertFalse(result["new_entries_allowed"])
        self.assertTrue(result["symbol_blocked"])
        self.assertEqual(result["readiness_score_cap"], 85)

    def test_micro_drawdown_full_lockout_blocks_orders_without_persistent_freeze(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update(self.mod.pmo_micro_account_mode_updates())
        original_lock = self.mod.PMO_DRAWDOWN_LOCK_FILE
        with tempfile.TemporaryDirectory() as tmp:
            self.mod.PMO_DRAWDOWN_LOCK_FILE = Path(tmp) / "drawdown_lock.json"
            try:
                result = self.mod.pmo_day_drawdown_governor(
                    settings,
                    {"ok": True, "equity": 200, "day_pnl": -6.25, "day_pnl_percent": -3.03},
                    symbol="SPY",
                    action="NEW_ENTRY",
                    record=True,
                )
            finally:
                self.mod.PMO_DRAWDOWN_LOCK_FILE = original_lock
        self.assertEqual(result["display_level"], "MAX_DRAWDOWN_REVIEW")
        self.assertEqual(result["micro_stage"], "FULL_LOCKOUT")
        self.assertFalse(result["session_frozen"])
        self.assertTrue(result["max_drawdown_review_now"])
        self.assertFalse(result["new_entries_allowed"])
        self.assertTrue(result["order_submission_blocked"])
        self.assertFalse(result["live_ready_allowed"])
        self.assertEqual(result["readiness_score_cap"], 55)

    def test_micro_execution_guard_blocks_high_risk_and_non_stock_symbols(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update(self.mod.pmo_micro_account_mode_updates())
        safe = self.mod.pmo_micro_execution_guard(settings, "MSFT", "STOCK", positions=[], require_proof=False)
        leveraged = self.mod.pmo_micro_execution_guard(settings, "TQQQ", "STOCK", positions=[], require_proof=False)
        crypto = self.mod.pmo_micro_execution_guard(settings, "BTC/USD", "CRYPTO", positions=[], require_proof=False)
        self.assertTrue(safe["allowed"])
        self.assertFalse(leveraged["allowed"])
        self.assertFalse(crypto["allowed"])

    def test_micro_learning_gate_requires_twenty_closed_paper_outcomes(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update(self.mod.pmo_micro_account_mode_updates())
        thin = self.mod.pmo_positive_learning_gate(
            settings,
            {"summary": {"clean_paper_replays": 10, "wins": 10, "losses": 0, "win_rate": 1.0}},
        )
        proven = self.mod.pmo_positive_learning_gate(
            settings,
            {
                "summary": {
                    "clean_paper_replays": 20,
                    "wins": 12,
                    "losses": 8,
                    "win_rate": 0.6,
                    "profit_factor": 1.5,
                    "expectancy_pct": 0.4,
                }
            },
        )
        self.assertFalse(thin["positive_allowed"])
        self.assertEqual(thin["min_rows"], 20)
        self.assertTrue(proven["positive_allowed"])

    def test_micro_learning_gate_rejects_unclean_or_unprofitable_outcomes(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update(self.mod.pmo_micro_account_mode_updates())
        unclean = self.mod.pmo_positive_learning_gate(
            settings,
            {
                "summary": {
                    "paper_replays": 30,
                    "clean_paper_replays": 0,
                    "wins": 30,
                    "losses": 0,
                    "win_rate": 1.0,
                    "profit_factor": 3.0,
                    "expectancy_pct": 2.0,
                }
            },
        )
        unprofitable = self.mod.pmo_positive_learning_gate(
            settings,
            {
                "summary": {
                    "clean_paper_replays": 20,
                    "wins": 12,
                    "losses": 8,
                    "win_rate": 0.6,
                    "profit_factor": 0.9,
                    "expectancy_pct": -0.1,
                }
            },
        )
        self.assertFalse(unclean["positive_allowed"])
        self.assertIn("clean true paper replay", unclean["reason"])
        self.assertFalse(unprofitable["positive_allowed"])
        self.assertIn("profit factor", unprofitable["reason"])

    def test_v112_rows_sync_to_sqlite_paper_outcomes(self):
        original_db = self.mod.PMO_STORAGE_DB
        with tempfile.TemporaryDirectory() as tmp:
            self.mod.PMO_STORAGE_DB = Path(tmp) / "pmo_storage.sqlite3"
            try:
                result = self.mod.pmo_sync_v112_rows_to_sqlite([
                    {
                        "replay_id": "PMO-TEST-OUTCOME-1",
                        "timestamp": "2026-06-06T10:00:00-04:00",
                        "closed_at": "2026-06-06T10:05:00-04:00",
                        "symbol": "SPY",
                        "market": "STOCK",
                        "replay_type": "PAPER_REPLAY",
                        "side": "BUY_LONG",
                        "setup_type": "PAPER_SETUP:LONG",
                        "entry_price": 100,
                        "stop_loss_price": 98,
                        "take_profit_price": 104,
                        "exit_price": 104,
                        "profit_loss_usd": 4,
                        "profit_loss_pct": 4,
                        "win_loss_result": "WIN",
                        "market_regime": "BULLISH",
                        "pmo_score": 80,
                        "rules_followed": True,
                    }
                ])
                self.assertTrue(result["ok"])
                self.assertEqual(result["synced"], 1)
                conn = sqlite3.connect(self.mod.PMO_STORAGE_DB)
                try:
                    row = conn.execute(
                        "SELECT symbol, result, rules_followed, pnl_pct FROM paper_outcomes WHERE trade_id = ?",
                        ("PMO-TEST-OUTCOME-1",),
                    ).fetchone()
                finally:
                    conn.close()
                self.assertEqual(row, ("SPY", "WIN", 1, 4.0))
            finally:
                self.mod.PMO_STORAGE_DB = original_db

    def test_stability_snapshot_reports_watchdog_storage_and_safety(self):
        original_db = self.mod.PMO_STORAGE_DB
        with tempfile.TemporaryDirectory() as tmp:
            self.mod.PMO_STORAGE_DB = Path(tmp) / "pmo_storage.sqlite3"
            try:
                settings = dict(self.mod.DEFAULT_SETTINGS)
                settings.update({
                    "ALPACA_PAPER": True,
                    "PMO_DRY_RUN_ORDERS": True,
                    "PMO_LIVE_TRADING_ENABLED": False,
                    "PMO_ALLOW_LIVE_TRADING": False,
                })
                snapshot = self.mod.pmo_system_stability_snapshot(
                    settings=settings,
                    health={"online": 3, "total": 3, "connections": []},
                    log_health={"status": "CLEAN", "critical_count": 0, "rows": []},
                    report_log_bar={"last_error": "No recent critical errors logged"},
                    record=True,
                )
                self.assertTrue(snapshot["ok"])
                self.assertTrue(snapshot["storage"]["initialized"])
                self.assertIn("Live safety locked", [row["name"] for row in snapshot["checks"] if row["ready"]])
                conn = sqlite3.connect(self.mod.PMO_STORAGE_DB)
                try:
                    count = conn.execute("SELECT COUNT(*) FROM system_events WHERE event_type = 'STABILITY_SNAPSHOT'").fetchone()[0]
                finally:
                    conn.close()
                self.assertGreaterEqual(count, 1)
            finally:
                self.mod.PMO_STORAGE_DB = original_db

    def test_log_health_keeps_playz_errors_out_of_pmo_bot_blockers(self):
        original_dir = self.mod.PMO_DIR
        original_runtime = self.mod.PMO_RUNTIME_LOG_DIR
        with tempfile.TemporaryDirectory() as tmp:
            temp_dir = Path(tmp)
            runtime_dir = temp_dir / "pmo_runtime_logs"
            runtime_dir.mkdir()
            (temp_dir / "pmo_bot_8091_stderr.log").write_text("WARNING: Flask dev server\n", encoding="utf-8")
            (temp_dir / "pmo_playz_8092_stderr.log").write_text("Traceback (most recent call last):\n", encoding="utf-8")
            old_runtime_log = temp_dir / "pmo_watchdog_dashboard_20260606_100000.err.log"
            current_runtime_log = temp_dir / "pmo_watchdog_dashboard_20260606_110000.err.log"
            old_runtime_log.write_text("Traceback (most recent call last):\n", encoding="utf-8")
            current_runtime_log.write_text("WARNING: Flask dev server\n", encoding="utf-8")
            now = time.time()
            os.utime(old_runtime_log, (now - 10, now - 10))
            os.utime(current_runtime_log, (now, now))
            try:
                self.mod.PMO_DIR = temp_dir
                self.mod.PMO_RUNTIME_LOG_DIR = runtime_dir
                snapshot = self.mod.pmo_log_health_snapshot()
                self.assertEqual(snapshot["critical_count"], 0)
                self.assertEqual(snapshot["reported_critical_count"], 2)
                self.assertEqual(snapshot["external_or_stale_critical_count"], 2)
                playz_rows = [row for row in snapshot["rows"] if row["component"] == "PMO Playz"]
                self.assertEqual(playz_rows[0]["status"], "EXTERNAL")
            finally:
                self.mod.PMO_DIR = original_dir
                self.mod.PMO_RUNTIME_LOG_DIR = original_runtime

    def test_executor_gate_blocks_live_master_and_dry_run(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "ENABLE_PMO_MICRO_ACCOUNT_MODE": False,
            "ENABLE_ALPACA_ORDER_EXECUTOR": True,
            "PMO_ORDER_EXECUTION_MODE": "LIVE_ALPACA",
            "ORDER_AUTOMATION_ENABLED": False,
            "PMO_DRY_RUN_ORDERS": True,
            "ALPACA_PAPER": True,
            "PMO_ALLOW_LIVE_TRADING": False,
            "PMO_LIVE_TRADING_ENABLED": False,
            "PMO_REQUIRE_PAPER_PROOF_FOR_LIVE_EXECUTOR": True,
        })
        result = self._run_executor_gate_test(settings, {"market_data": {"ok": True, "price": 100}, "score": 95})
        blockers = " | ".join(result["blocked"])
        self.assertIn("ORDER_AUTOMATION_ENABLED is OFF", blockers)
        self.assertIn("PMO_DRY_RUN_ORDERS is ON", blockers)
        self.assertIn("LIVE_ALPACA requires ALPACA_PAPER=False", blockers)
        self.assertIn("live master and live permission switches must both be ON", blockers)
        self.assertFalse(result["submitted"])

    def test_executor_gate_blocks_missing_market_data_duplicate_and_protective_plan(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "ENABLE_PMO_MICRO_ACCOUNT_MODE": False,
            "ENABLE_ALPACA_ORDER_EXECUTOR": True,
            "PMO_ORDER_EXECUTION_MODE": "PAPER_ALPACA",
            "ORDER_AUTOMATION_ENABLED": True,
            "PMO_DRY_RUN_ORDERS": False,
            "ALPACA_PAPER": True,
            "PMO_REQUIRE_MARKET_DATA_FOR_EXECUTION": True,
            "PMO_REQUIRE_PROTECTIVE_EXIT_PLAN": True,
        })
        result = self._run_executor_gate_test(
            settings,
            {"market_data": {"ok": False}, "score": 90},
            open_orders=[{"symbol": "SPY"}],
            payload={"notional": 10},
        )
        blockers = " | ".join(result["blocked"])
        self.assertIn("live market data is required before execution", blockers)
        self.assertIn("duplicate open order already exists for SPY", blockers)
        self.assertIn("protective trade plan blocked execution", blockers)
        self.assertFalse(result["submitted"])

    def test_multi_account_paper_bus_routes_to_enabled_profiles(self):
        class FakeMarketOrderRequest:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeOrderSide:
            BUY = "buy"

        class FakeTimeInForce:
            DAY = "day"
            GTC = "gtc"

        class FakeAccount:
            equity = 100000
            last_equity = 100000
            buying_power = 100000
            cash = 100000
            portfolio_value = 100000
            daytrading_buying_power = 100000
            daytrade_count = 0
            pattern_day_trader = False
            trading_blocked = False
            account_blocked = False
            shorting_enabled = False
            status = "ACTIVE"

        class FakeSubmittedOrder:
            id = "order-1"
            client_order_id = "client-1"
            symbol = "SPY"
            qty = ""
            notional = "100"
            side = "buy"
            status = "accepted"

        class FakeClient:
            def __init__(self, profile):
                self.profile = profile
                self.submitted = []

            def get_account(self):
                return FakeAccount()

            def get_all_positions(self):
                return []

            def get_orders(self):
                return []

            def submit_order(self, order_data=None):
                self.submitted.append(order_data)
                return FakeSubmittedOrder()

        bot = self.mod.bot
        clients = {"PMO_BOT2": FakeClient("PMO_BOT2"), "PMO_WHALE": FakeClient("PMO_WHALE")}
        original_settings = bot.settings
        original_market_order_request = self.mod.MarketOrderRequest
        original_order_side = self.mod.OrderSide
        original_time_in_force = self.mod.TimeInForce
        original_client_for_profile = bot.alpaca_trading_client_for_profile
        original_paper_execution_profiles = bot.paper_execution_profiles
        original_connection_check = bot.connection_check
        original_market_regime = bot.market_regime
        original_drawdown = self.mod.pmo_day_drawdown_governor
        original_smart_limits = self.mod.pmo_smart_trade_limit_snapshot
        original_paper_proof = self.mod.pmo_paper_proof_snapshot
        original_order_file = self.mod.PMO_ORDER_EXECUTION_FILE
        original_order_prestage_file = self.mod.PMO_ORDER_PRESTAGE_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.mod.PMO_ORDER_EXECUTION_FILE = Path(tmp) / "pmo_order_execution.csv"
                self.mod.PMO_ORDER_PRESTAGE_FILE = Path(tmp) / "pmo_order_prestage.json"
                settings = dict(self.mod.DEFAULT_SETTINGS)
                settings.update({
                    "ENABLE_PMO_MULTI_ACCOUNT_PAPER_EXECUTION": True,
                    "PMO_PAPER_EXECUTION_PROFILES": ["PMO_BOT2", "PMO_WHALE"],
                    "PMO_AGGRESSIVE_PAPER_PROFILES": ["PMO_WHALE"],
                    "ENABLE_PMO_MICRO_ACCOUNT_MODE": False,
                    "ENABLE_ALPACA_ORDER_EXECUTOR": True,
                    "PMO_ORDER_EXECUTION_MODE": "PAPER_ALPACA",
                    "ORDER_AUTOMATION_ENABLED": True,
                    "PMO_DRY_RUN_ORDERS": False,
                    "ALPACA_PAPER": True,
                    "ENABLE_PMO_SCORE_REBUILD_GATES": False,
                    "ENABLE_PMO_OPENING_HOUR_QUALITY_GATES": False,
                    "PMO_WHY_NOT_REQUIRE_RVOL": False,
                    "ENABLE_PMO_WHY_NOT_VWAP_BLOCKER": False,
                    "PMO_WHY_NOT_REQUIRE_VWAP_DATA": False,
                    "ENABLE_PMO_PAPER_PROOF_QUALITY_BREAKER": False,
                    "ENABLE_PMO_PAPER_EXECUTOR_COLLECTION_MODE": True,
                    "PMO_REQUIRE_MARKET_DATA_FOR_EXECUTION": True,
                    "PMO_REQUIRE_PROTECTIVE_EXIT_PLAN": True,
                    "PMO_SCORE_PAPER_ONLY_MIN": 65,
                    "PMO_PAPER_EXECUTOR_MIN_SCORE": 65,
                    "PMO_AGGRESSIVE_PAPER_EXECUTOR_MIN_SCORE": 65,
                    "PMO_MAX_DAILY_TRADES": 10,
                    "PMO_MAX_TRADES_BY_MARKET": {"STOCK": 10, "CRYPTO": 0, "OPTION": 0},
                })
                bot.settings = settings
                self.mod.MarketOrderRequest = FakeMarketOrderRequest
                self.mod.OrderSide = FakeOrderSide
                self.mod.TimeInForce = FakeTimeInForce
                bot.alpaca_trading_client_for_profile = lambda profile: clients[self.mod.env_key_slug(profile)]
                bot.paper_execution_profiles = lambda: ["PMO_BOT2", "PMO_WHALE"]
                bot.connection_check = lambda: {"online": 10, "total": 10, "connections": []}
                bot.market_regime = lambda: {"regime": "BULLISH", "risk_multiplier": 1.0, "volatility_pressure": False}
                self.mod.pmo_day_drawdown_governor = lambda *args, **kwargs: {"symbol_blocked": False, "blockers": [], "live_ready_allowed": False}
                self.mod.pmo_smart_trade_limit_snapshot = lambda *args, **kwargs: {
                    "execution_allowed": True,
                    "effective_max_daily_trades": 10,
                    "effective_by_market": {"STOCK": 10},
                    "limit_mode": "TEST",
                    "score_band": {},
                }
                self.mod.pmo_paper_proof_snapshot = lambda settings=None, record=False: {"ready_to_unlock_live": False, "score": 0, "status": "PROOF BUILDING"}
                decision = {
                    "symbol": "SPY",
                    "side": "LONG",
                    "score": 70,
                    "market_data": {"ok": True, "price": 100},
                }
                result = bot.submit_order_from_decision(decision, {"price": 100, "notional": 100})
                self.assertTrue(result["multi_account"])
                self.assertEqual(set(result["submitted_profiles"]), {"PMO_BOT2", "PMO_WHALE"})
                self.assertEqual(len(clients["PMO_BOT2"].submitted), 1)
                self.assertEqual(len(clients["PMO_WHALE"].submitted), 1)
                rows = self.mod.recent_csv_rows(self.mod.PMO_ORDER_EXECUTION_FILE, 10)
                self.assertEqual({row.get("alpaca_profile") for row in rows}, {"PMO_BOT2", "PMO_WHALE"})
        finally:
            bot.settings = original_settings
            self.mod.MarketOrderRequest = original_market_order_request
            self.mod.OrderSide = original_order_side
            self.mod.TimeInForce = original_time_in_force
            bot.alpaca_trading_client_for_profile = original_client_for_profile
            bot.paper_execution_profiles = original_paper_execution_profiles
            bot.connection_check = original_connection_check
            bot.market_regime = original_market_regime
            self.mod.pmo_day_drawdown_governor = original_drawdown
            self.mod.pmo_smart_trade_limit_snapshot = original_smart_limits
            self.mod.pmo_paper_proof_snapshot = original_paper_proof
            self.mod.PMO_ORDER_EXECUTION_FILE = original_order_file
            self.mod.PMO_ORDER_PRESTAGE_FILE = original_order_prestage_file

    def test_execution_firewall_never_allows_live_with_paper_mode(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "ALPACA_PAPER": True,
            "PMO_ALLOW_LIVE_TRADING": False,
            "PMO_LIVE_TRADING_ENABLED": False,
            "ORDER_AUTOMATION_ENABLED": True,
            "PMO_DRY_RUN_ORDERS": False,
            "ENABLE_ALPACA_ORDER_EXECUTOR": True,
            "PMO_ORDER_EXECUTION_MODE": "PAPER_ALPACA",
        })
        result = self.mod.pmo_execution_firewall_snapshot(
            settings=settings,
            account={"equity": 200, "buying_power": 200, "trading_blocked": False, "account_blocked": False},
            health={"online": 3, "total": 3},
            regime={"regime": "BULLISH", "risk_multiplier": 1.0},
            record=False,
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["live_order_allowed"])
        self.assertIn("live locked: Alpaca paper mode is ON", result["locks"])

    def test_trade_discipline_blocks_without_confirmations(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "ENABLE_PMO_TRADE_DISCIPLINE_CHECKS": True,
            "ENABLE_PMO_DISCIPLINE_WHY_NOT_BLOCKERS": True,
            "PMO_DISCIPLINE_MIN_CONFIRMATIONS": 2,
            "PMO_WHY_NOT_MIN_SCORE": 78,
            "PMO_WHY_NOT_MIN_RVOL": 1.5,
        })
        result = self.mod.pmo_trade_discipline_check(
            {"symbol": "SPY", "score": 40, "relative_volume": 0.5, "bias": "WAIT", "notional": 40},
            settings,
            regime={"regime": "UNKNOWN", "risk_multiplier": 1.0},
        )
        self.assertEqual(result["status"], "BLOCK")
        self.assertGreaterEqual(len(result["blockers"]), 1)
        self.assertFalse(result["live_order_allowed"])

    def test_opening_hour_quality_gate_passes_clean_opening_long(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        row = {
            "symbol": "SPY",
            "side": "LONG",
            "timestamp": "2026-06-16T09:45:00-04:00",
            "relative_volume": 2.4,
            "edge_engines": {
                "edge_engine_status": "READY",
                "gap_signal": "GAP_UP_HOLD",
                "orb_signal": "BULLISH",
            },
        }
        result = self.mod.pmo_opening_hour_quality_gate("SPY", "LONG", "CALL_BIAS", row, settings, 2.4)
        self.assertTrue(result["active"])
        self.assertTrue(result["allowed"])
        confirmations = " | ".join(result["confirmations"])
        self.assertIn("opening RVOL gate passed", confirmations)
        self.assertIn("opening ORB gate passed", confirmations)

    def test_opening_hour_quality_gate_blocks_weak_opening_long(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        row = {
            "symbol": "SPY",
            "side": "LONG",
            "timestamp": "2026-06-16T09:34:00-04:00",
            "relative_volume": 1.2,
            "edge_engines": {
                "edge_engine_status": "READY",
                "gap_signal": "GAP_UP_FILL",
                "orb_signal": "INSIDE",
            },
        }
        result = self.mod.pmo_opening_hour_quality_gate("SPY", "LONG", "CALL_BIAS", row, settings, 1.2)
        self.assertTrue(result["active"])
        self.assertFalse(result["allowed"])
        blockers = " | ".join(result["blockers"])
        self.assertIn("wait until 09:40", blockers)
        self.assertIn("opening RVOL gate", blockers)
        self.assertIn("GAP_UP_HOLD", blockers)
        self.assertIn("ORB BULLISH", blockers)

    def test_post_gate_equity_proof_counts_only_post_gate_equity(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "PMO_POST_GATE_EQUITY_PROOF_START": "2026-06-16T00:00:00-04:00",
            "PMO_POST_GATE_EQUITY_MIN_CLOSED_TRADES": 2,
            "PMO_POST_GATE_EQUITY_MIN_WIN_RATE": 0.5,
            "PMO_POST_GATE_EQUITY_MIN_PROFIT_FACTOR": 1.0,
        })
        rows = [
            {"timestamp": "2026-06-16T09:34:00-04:00", "symbol": "SPY", "status": "CLOSED_LOSS", "pnl": "-1.0"},
            {"timestamp": "2026-06-16T09:45:00-04:00", "symbol": "SPY", "status": "CLOSED_WIN", "pnl": "2.0"},
            {"timestamp": "2026-06-16T11:00:00-04:00", "symbol": "XLP", "status": "CLOSED_LOSS", "pnl": "-1.0"},
            {"timestamp": "2026-06-16T20:00:00-04:00", "symbol": "SOL/USD", "status": "CLOSED_WIN", "pnl": "3.0"},
        ]
        original_rows = self.mod.pmo_closed_trade_rows_for_learning
        try:
            self.mod.pmo_closed_trade_rows_for_learning = lambda *args, **kwargs: rows
            proof = self.mod.pmo_post_gate_equity_proof_snapshot(settings)
        finally:
            self.mod.pmo_closed_trade_rows_for_learning = original_rows
        self.assertEqual(proof["summary"]["closed"], 2)
        self.assertEqual(proof["summary"]["wins"], 1)
        self.assertEqual(proof["summary"]["losses"], 1)
        self.assertEqual(proof["excluded_counts"]["pre_gate_opening_slot"], 1)
        self.assertEqual(proof["excluded_counts"]["non_equity"], 1)
        self.assertTrue(proof["ready"])

    def test_elite_signals_ensemble_normalizes_options_social_and_carry_votes(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "PMO_ENSEMBLE_MIN_BULL_VOTES": 6,
            "PMO_ENSEMBLE_MIN_AGREE_RATIO": 0.6,
        })
        candidate = {
            "pattern_direction": "long",
            "fvg_signal": "BULLISH",
            "edge_signal": "BULLISH",
            "intel_signal": "BULLISH",
            "ml_signal": "BULLISH",
            "vwap_score_status": "PASS",
            "relative_volume": 2.5,
        }
        report = self.mod.pmo_analyze_elite_signals(
            "SPY",
            "long",
            settings,
            candidate=candidate,
            options_events=[{"symbol": "SPY", "option_type": "CALL", "contracts": 1500, "premium": 250000, "dte": 3, "minutes_ago": 12}],
            social_samples=[{"symbol": "SPY", "mentions": 300, "baseline_mentions": 30}],
            usdjpy_bars=[{"close": 150.0}, {"close": 149.4}],
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["options_flow"]["vote"]["side"], "BULL")
        self.assertEqual(report["social_velocity"]["vote"]["side"], "BULL")
        self.assertEqual(report["usdjpy_carry"]["vote"]["side"], "BEAR")
        self.assertEqual(report["ensemble"]["status"], "BULLISH_ENSEMBLE")
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["live_unlocked"])

    def test_walk_forward_validation_uses_later_unseen_rows(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "PMO_WALK_FORWARD_MIN_TRAIN_ROWS": 2,
            "PMO_WALK_FORWARD_MIN_TEST_ROWS": 2,
            "PMO_WALK_FORWARD_MIN_TEST_WIN_RATE": 0.5,
        })
        rows = [
            {"timestamp": "2026-06-01T10:00:00-04:00", "symbol": "AAPL", "status": "CLOSED_WIN", "pnl": "1", "edge_signal": "BULLISH"},
            {"timestamp": "2026-06-02T10:00:00-04:00", "symbol": "AAPL", "status": "CLOSED_LOSS", "pnl": "-1", "edge_signal": "BULLISH"},
            {"timestamp": "2026-06-03T10:00:00-04:00", "symbol": "AAPL", "status": "CLOSED_WIN", "pnl": "1", "edge_signal": "BULLISH"},
            {"timestamp": "2026-06-04T10:00:00-04:00", "symbol": "AAPL", "status": "CLOSED_LOSS", "pnl": "-1", "edge_signal": "BULLISH"},
        ]
        original_rows = self.mod.pmo_closed_trade_rows_for_learning
        try:
            self.mod.pmo_closed_trade_rows_for_learning = lambda *args, **kwargs: rows
            report = self.mod.pmo_walk_forward_validation_report(settings, record=False)
        finally:
            self.mod.pmo_closed_trade_rows_for_learning = original_rows
        wf = report["report"]
        self.assertEqual(wf["train_rows"], 2)
        self.assertEqual(wf["test_rows"], 2)
        edge_validation = next(row for row in wf["validations"] if row["field"] == "edge_signal")
        self.assertTrue(edge_validation["validated"])

    def test_alpha_decay_profiler_profiles_ticker_specific_params(self):
        alpha_mod = load_local_module("pmo_alpha_decay")
        rows = [
            {"timestamp": "2026-06-01T10:00:00-04:00", "symbol": "NVDA", "status": "CLOSED_WIN", "pnl": "4.0", "hold_minutes": "10"},
            {"timestamp": "2026-06-02T10:00:00-04:00", "symbol": "NVDA", "status": "CLOSED_WIN", "pnl": "3.5", "hold_minutes": "12"},
            {"timestamp": "2026-06-03T10:00:00-04:00", "symbol": "NVDA", "status": "CLOSED_WIN", "pnl": "3.0", "hold_minutes": "15"},
            {"timestamp": "2026-06-04T10:00:00-04:00", "symbol": "NVDA", "status": "CLOSED_LOSS", "pnl": "-2.0", "hold_minutes": "34"},
            {"timestamp": "2026-06-05T10:00:00-04:00", "symbol": "HOOD", "status": "CLOSED_WIN", "pnl": "9.0", "hold_minutes": "5"},
        ]
        profiler = alpha_mod.AlphaDecayProfiler(min_trades=3, confident_trades=4)
        loaded = profiler.load(rows)
        profile = profiler.get_profile("NVDA")
        params = profiler.get_optimal_params("NVDA", min_confidence="LOW")

        self.assertEqual(loaded, 4)
        self.assertIsNotNone(profile)
        self.assertEqual(profile.move_profile, "FAST_BURST")
        self.assertEqual(profile.confidence, "HIGH")
        self.assertEqual(params["source"], "TICKER_PROFILE")
        self.assertLessEqual(params["tp_pct"], 5.0)
        self.assertEqual(profiler.get_profile("HOOD"), None)

    def test_alpha_decay_api_is_read_only_and_does_not_unlock_live(self):
        response = self.client.get("/api/alpha-decay/summary")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["alpha_decay"]
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["orders_placed"])
        self.assertFalse(payload["live_unlocked"])
        self.assertFalse(payload["settings_changed"])

        params_response = self.client.get("/api/alpha-decay/params/SPY")
        self.assertEqual(params_response.status_code, 200)
        params = params_response.get_json()
        self.assertTrue(params["read_only"])
        self.assertFalse(params["orders_placed"])
        self.assertFalse(params["live_unlocked"])
        disabled = dict(self.mod.DEFAULT_SETTINGS)
        disabled["PMO_ALPHA_DECAY_ENABLED"] = False
        disabled_params = self.mod.pmo_alpha_decay_params("SPY", disabled)
        self.assertFalse(disabled_params["enabled"])
        self.assertEqual(disabled_params["source"], "DISABLED")

    def test_institutional_signals_cover_all_requested_edges(self):
        inst_mod = load_local_module("pmo_institutional_signals")
        settings = dict(self.mod.DEFAULT_SETTINGS)
        bars = []
        for idx, close in enumerate(list(range(100, 110)) + list(range(112, 123))):
            bars.append({"timestamp": f"2026-06-17T10:{idx:02d}:00-04:00", "open": close - 0.2, "high": close + 0.4, "low": close - 0.4, "close": close, "volume": 1000})
        bars.append({"timestamp": "2026-06-17T10:30:00-04:00", "open": 110.2, "high": 110.8, "low": 110.0, "close": 110.5, "volume": 1800})
        report = inst_mod.analyze_institutional_signals(
            "SPY",
            settings,
            bars=bars,
            candidate={"symbol": "SPY", "bias": "CALL_BIAS", "time": "15:35", "change_pct": 1.2},
            quotes=[
                {"symbol": "SPY", "price": 101.0, "bid": 100.9, "ask": 101.0},
                {"symbol": "SPY", "price": 101.1, "bid": 101.0, "ask": 101.1},
                {"symbol": "SPY", "price": 101.2, "bid": 101.1, "ask": 101.2},
            ],
            earnings_rows=[{"symbol": "SPY", "earnings_date": "2026-06-14", "surprise_pct": "8.5", "result": "BEAT"}],
            iv_rows=[{"symbol": "SPY", "iv_rank": "76", "implied_volatility": "0.52", "realized_volatility": "0.31"}],
            earnings_text="Revenue increased 23 percent, EPS was 2.31, margin reached 14 percent, cash flow was 1.2 billion.",
            market_change_pct=1.2,
            now_value="2026-06-17T15:35:00",
        )
        signals = report["signals"]
        self.assertEqual(signals["liquidity_vacuum"]["status"], "READY")
        self.assertNotEqual(signals["auction_vwap_atr"]["status"], "DATA_REQUIRED")
        self.assertTrue(signals["three_thirty_effect"]["hard_block"])
        self.assertEqual(signals["earnings_language"]["status"], "READY")
        self.assertEqual(signals["ask_side_prints"]["status"], "READY")
        self.assertEqual(signals["pead"]["status"], "READY")
        self.assertEqual(signals["volatility_risk_premium"]["status"], "READY")
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["live_unlocked"])

    def test_institutional_signals_api_is_read_only(self):
        response = self.client.post(
            "/api/institutional-signals",
            json={
                "symbol": "SPY",
                "candidate": {"symbol": "SPY", "bias": "CALL_BIAS", "time": "15:35", "change_pct": 1.0},
                "market_change_pct": 1.0,
                "now": "2026-06-17T15:35:00",
                "bars": [],
                "quotes": [],
                "earnings_rows": [],
                "iv_rows": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        report = response.get_json()["institutional_signals"]
        self.assertTrue(report["read_only"])
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["live_unlocked"])
        self.assertEqual(report["signals"]["three_thirty_effect"]["status"], "BLOCK")

    def test_deep_intelligence_detects_drift_asymmetry_and_crowding(self):
        deep_mod = load_local_module("pmo_deep_intelligence")
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "PMO_CONCEPT_DRIFT_ROLLING_WINDOW": 5,
            "PMO_CONCEPT_DRIFT_ALERT_DROP": 0.15,
            "PMO_CAUSAL_MIN_ROWS": 10,
        })
        trades = []
        for idx in range(10):
            trades.append({"timestamp": f"2026-06-01T10:{idx:02d}:00-04:00", "symbol": "SPY", "status": "CLOSED_WIN", "pnl": "1", "relative_volume": "2.5"})
        for idx in range(5):
            trades.append({"timestamp": f"2026-06-02T10:{idx:02d}:00-04:00", "symbol": "SPY", "status": "CLOSED_LOSS", "pnl": "-1", "relative_volume": "0.8"})
        bars = [
            {"timestamp": "2026-06-17T10:00:00-04:00", "open": 100, "high": 101, "low": 99, "close": 100, "relative_volume": 1.0},
            {"timestamp": "2026-06-17T10:05:00-04:00", "open": 100, "high": 105, "low": 99.5, "close": 104, "relative_volume": 4.2},
            {"timestamp": "2026-06-17T10:10:00-04:00", "open": 104, "high": 104.5, "low": 100, "close": 100.5, "relative_volume": 0.7},
            {"timestamp": "2026-06-17T10:15:00-04:00", "open": 100.5, "high": 101, "low": 99, "close": 99.5, "relative_volume": 0.9},
        ]
        report = deep_mod.analyze_deep_intelligence(
            "SPY",
            settings,
            trades=trades,
            bars=bars,
            candidate={"symbol": "SPY", "relative_volume": 4.1, "change_pct": 3.4},
            news_rows=[],
            earnings_rows=[],
            market_rows=[{"timestamp": "2026-06-16T16:00:00-04:00", "regime": "DEFENSIVE", "change_pct": "-0.8"}],
            now_value="2026-06-17T10:20:00-04:00",
        )
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["live_unlocked"])
        self.assertEqual(report["signals"]["concept_drift"]["status"], "ALERT")
        self.assertEqual(report["signals"]["information_asymmetry"]["status"], "DETECTED")
        self.assertEqual(report["signals"]["adversarial_examples"]["status"], "ALERT")
        self.assertIn(report["signals"]["emergent_behavior"]["status"], {"CROWDING_DETECTED", "CLEAR"})
        self.assertLess(report["recommended_position_size_multiplier"], 1.0)
        guidance = report["operational_guidance"]
        self.assertEqual(guidance["status"], "CAUTION")
        self.assertLess(guidance["position_size_multiplier"], 1.0)
        self.assertIn(guidance["attention_signal"], {"BULLISH_ATTENTION", "NEUTRAL_ATTENTION", "BEARISH_ATTENTION"})
        self.assertIn("bayesian_size_multiplier", guidance)
        self.assertIn("causal_trust_multiplier", guidance)
        self.assertIn("meta_adaptation_multiplier", guidance)
        self.assertIn("exit_policy", guidance)

    def test_deep_intelligence_endpoint_is_read_only(self):
        response = self.client.post(
            "/api/deep-intelligence",
            json={
                "symbol": "SPY",
                "trades": [{"timestamp": "2026-06-17T10:00:00-04:00", "symbol": "SPY", "status": "CLOSED_WIN", "pnl": "1"}],
                "bars": [{"timestamp": "2026-06-17T10:05:00-04:00", "open": 100, "high": 101, "low": 99, "close": 100, "relative_volume": 1}],
            },
        )
        self.assertEqual(response.status_code, 200)
        report = response.get_json()["deep_intelligence"]
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["live_unlocked"])
        self.assertFalse(report["settings_changed"])
        self.assertIn("concept_drift", report["signals"])
        self.assertIn("bayesian_edge", report["signals"])
        self.assertIn("operational_guidance", report)
        self.assertFalse(report["operational_guidance"]["score_mod_applied"])

    def test_frontier_intelligence_covers_all_requested_layers(self):
        frontier_mod = load_local_module("pmo_frontier_intelligence")
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "PMO_FRONTIER_MONTE_CARLO_PATHS": 200,
            "PMO_FRONTIER_SELF_MOD_WINDOW_TRADES": 10,
        })
        bars = []
        price = 100.0
        for idx in range(14):
            price += 0.9
            bars.append({"timestamp": f"2026-06-17T10:{idx:02d}:00-04:00", "open": price - 0.4, "high": price + 0.7, "low": price - 0.6, "close": price, "volume": 1000 + idx * 80})
        trades = []
        for idx in range(6):
            trades.append({"timestamp": f"2026-06-01T10:{idx:02d}:00-04:00", "symbol": "SPY", "status": "CLOSED_LOSS", "pnl": "-1", "max_drawdown_pct": "2.8", "hold_minutes": "18"})
        for idx in range(4):
            trades.append({"timestamp": f"2026-06-02T10:{idx:02d}:00-04:00", "symbol": "SPY", "status": "CLOSED_WIN", "pnl": "1", "hold_minutes": "12"})
        report = frontier_mod.analyze_frontier_intelligence(
            "SPY",
            settings,
            candidate={"symbol": "SPY", "side": "LONG", "score": 76, "relative_volume": 3.0, "edge_score": 20, "intel_score": 82},
            bars=bars,
            trades=trades,
            macro_rows=[{"breadth_pct": 66, "credit_spread_bps": 260, "yield_curve_10y2y_bps": 35, "dxy_change_pct": -0.5, "cftc_net_position_z": 1.1, "vix_change_pct": -6}],
            narrative_rows=[{"symbol": "SPY", "theme": "AI infrastructure spending", "mentions": 180, "baseline_mentions": 30, "sentiment": 0.4}],
            news_rows=[{"symbol": "SPY", "headline": "AI guidance upgrade raises spending outlook"}],
            engine_history_rows=[
                {"score": 70, "relative_volume": 2.0, "edge_score": 65, "intel_score": 68},
                {"score": 72, "relative_volume": 2.1, "edge_score": 66, "intel_score": 69},
                {"score": 74, "relative_volume": 2.2, "edge_score": 67, "intel_score": 70},
                {"score": 76, "relative_volume": 2.3, "edge_score": 68, "intel_score": 71},
            ],
            fingerprints=[{"label": "June 2022 relief", "breadth_pct": 65, "vix_change_pct": -5, "credit_spread_bps": 270, "yield_curve_10y2y_bps": 30, "forward_20d_pct": 4.2}],
            now_value="2026-06-17T10:30:00-04:00",
        )
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["live_unlocked"])
        self.assertFalse(report["settings_changed"])
        for key in {"market_consciousness", "narrative_momentum", "reflexivity", "engine_divergence", "temporal_memory", "monte_carlo", "self_modification"}:
            self.assertIn(key, report["signals"])
        self.assertEqual(report["signals"]["market_consciousness"]["direction"], "RISK_ON")
        self.assertEqual(report["signals"]["narrative_momentum"]["status"], "READY")
        self.assertIn(report["signals"]["monte_carlo"]["status"], {"FAVORABLE", "LOW_CONFIDENCE", "TAIL_RISK"})
        self.assertEqual(report["signals"]["self_modification"]["status"], "PROPOSAL_READY")
        self.assertFalse(report["operational_guidance"]["score_mod_applied"])

    def test_frontier_intelligence_endpoint_is_read_only(self):
        response = self.client.post(
            "/api/frontier-intelligence",
            json={
                "symbol": "SPY",
                "candidate": {"symbol": "SPY", "side": "LONG", "score": 70},
                "bars": [{"timestamp": "2026-06-17T10:05:00-04:00", "close": 100, "volume": 1000}],
                "trades": [],
                "macro_rows": [],
                "narrative_rows": [],
                "engine_history_rows": [],
                "fingerprints": [],
            },
        )
        self.assertEqual(response.status_code, 200)
        report = response.get_json()["frontier_intelligence"]
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["live_unlocked"])
        self.assertFalse(report["settings_changed"])
        self.assertIn("market_consciousness", report["signals"])
        self.assertIn("monte_carlo", report["signals"])
        self.assertIn("operational_guidance", report)

    def test_advanced_ml_intelligence_covers_all_requested_layers(self):
        advanced_mod = load_local_module("pmo_advanced_ml_intelligence")
        report = advanced_mod.analyze_advanced_ml_intelligence(
            PMO_DIR / "pmo_csv" / "pmo_bot_trade_journal.csv",
            PMO_DIR / "pmo_csv" / "pmo_order_execution_journal.csv",
            symbol="SPY",
            settings={
                "PMO_ADVANCED_ML_MAX_ROWS": 5000,
                "PMO_ADVANCED_ML_SYNTHETIC_ROWS": 25,
            },
        )
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["live_trading_changed"])
        modules = report["modules"]
        for key in {
            "regime_conditional_models",
            "price_action_embeddings",
            "kalman_vwap",
            "rl_exit_timing",
            "conformal_prediction",
            "monte_carlo_dropout",
            "time_series_cross_validation",
            "decay_weighting",
            "stacked_engine_meta_learner",
            "kelly_with_uncertainty",
            "minimum_description_length",
            "synthetic_trade_generation",
        }:
            self.assertIn(key, modules)
        self.assertTrue(modules["synthetic_trade_generation"]["excluded_from_proof"])
        self.assertIn("stacking_status", report["journal"])
        self.assertIn("walk_forward_status", report["journal"])

    def test_advanced_ml_intelligence_endpoint_is_read_only(self):
        response = self.client.get("/api/ai/advanced-ml?symbol=SPY")
        self.assertEqual(response.status_code, 200)
        report = response.get_json()["advanced_ml"]
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["live_trading_changed"])
        self.assertIn("stacked_engine_meta_learner", report["modules"])
        self.assertIn("time_series_cross_validation", report["modules"])
        self.assertIn("minimum_description_length", report["modules"])

    def test_meta_strategy_layer_covers_cfr_and_system_meta_layers(self):
        meta_mod = load_local_module("pmo_meta_strategy_layer")
        report = meta_mod.analyze_meta_strategy_layer(
            PMO_DIR / "pmo_csv" / "pmo_bot_trade_journal.csv",
            PMO_DIR / "pmo_reports" / "pmo_why_not_latest.json",
            PMO_DIR / "pmo_csv" / "pmo_why_not_events.csv",
            settings={"PMO_META_MAX_ROWS": 5000, "PMO_META_SHADOW_EVENT_ROWS": 5000},
            current_state={"regime": "BULL", "score": 71, "rvol": 2.1, "pnl_today": 1.2, "trades_today": 2},
        )
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["settings_changed"])
        self.assertFalse(report["live_trading_changed"])
        modules = report["modules"]
        for key in {
            "counterfactual_regret_minimization",
            "regret_table",
            "adversarial_market_model",
            "attention_weighting",
            "alpha_decay_lead_time",
            "regime_model_router",
            "shadow_trade_tracker",
            "confidence_calibration",
            "prediction_error_model",
        }:
            self.assertIn(key, modules)
        distribution = modules["counterfactual_regret_minimization"]["action_distribution"]
        self.assertTrue({"TAKE_FULL", "TAKE_HALF", "WAIT_CONFIRMATION", "SKIP"}.issubset(distribution))
        self.assertIn("cfr_action", report["journal"])

    def test_meta_strategy_endpoint_is_read_only(self):
        response = self.client.post(
            "/api/ai/meta-strategy",
            json={"current_state": {"regime": "BULL", "score": 71, "rvol": 2.1}},
        )
        self.assertEqual(response.status_code, 200)
        report = response.get_json()["meta_strategy"]
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["settings_changed"])
        self.assertFalse(report["live_trading_changed"])
        self.assertIn("counterfactual_regret_minimization", report["modules"])
        self.assertIn("shadow_trade_tracker", report["modules"])

    def test_vault_intelligence_covers_all_vault_layers(self):
        vault_mod = load_local_module("pmo_vault_intelligence")
        report = vault_mod.analyze_vault_intelligence(
            PMO_DIR / "pmo_csv" / "pmo_bot_trade_journal.csv",
            settings={"PMO_VAULT_MAX_ROWS": 5000},
            current_state={"regime": "BULL", "score": 71, "rvol": 2.1},
        )
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["settings_changed"])
        self.assertFalse(report["live_trading_changed"])
        modules = report["modules"]
        for key in {
            "epigenetic_algorithm",
            "strange_attractor_detection",
            "bayesian_surprise",
            "eigenportfolio_decomposition",
            "symmetry_breaking",
            "mutual_information_maximization",
            "mechanism_design_probe",
        }:
            self.assertIn(key, modules)
        self.assertEqual(modules["mechanism_design_probe"]["status"], "SIMULATION_ONLY")
        self.assertIn("vault_top_information_feature", report["journal"])

    def test_vault_intelligence_endpoint_is_read_only(self):
        response = self.client.post(
            "/api/ai/vault-intelligence",
            json={"current_state": {"regime": "BULL", "score": 71, "rvol": 2.1}},
        )
        self.assertEqual(response.status_code, 200)
        report = response.get_json()["vault_intelligence"]
        self.assertTrue(report["ok"])
        self.assertTrue(report["read_only"])
        self.assertFalse(report["orders_placed"])
        self.assertFalse(report["settings_changed"])
        self.assertFalse(report["live_trading_changed"])
        self.assertIn("epigenetic_algorithm", report["modules"])
        self.assertIn("mechanism_design_probe", report["modules"])

    def test_trade_journal_quality_fields_include_meta_regret_tags(self):
        fields = self.mod.pmo_trade_journal_quality_fields(
            "SPY",
            {
                "score": 71,
                "relative_volume": 2.1,
                "entry_price": 100,
                "exit_price": 103,
                "side": "LONG",
                "market_regime": "BULL",
            },
            use_live_context=False,
        )
        self.assertEqual(fields["meta_layer_status"], "READ_ONLY_LOGGED")
        self.assertIn("TAKE_FULL", fields["meta_cfr_alternatives"])
        self.assertIn("TAKE_HALF", fields["meta_cfr_alternatives"])
        self.assertIn("WAIT_CONFIRMATION", fields["meta_cfr_alternatives"])
        self.assertIn("SKIP", fields["meta_cfr_alternatives"])
        self.assertIn("meta_attention_weight", fields)
        self.assertIn("meta_prediction_error_question", fields)

    def test_trade_journal_quality_fields_auto_logs_deep_exit_policy(self):
        original_report = self.mod.pmo_deep_intelligence_report
        try:
            self.mod.pmo_deep_intelligence_report = lambda *args, **kwargs: {
                "journal": {
                    "deep_status": "READY",
                    "deep_size_mult": 0.35,
                    "deep_score_mod_rec": 0,
                    "deep_attention_signal": "NEUTRAL_ATTENTION",
                    "deep_exit_policy": "LET_WINNERS_WORK",
                    "bayesian_confidence": "LOW",
                    "causal_trust_mult": 0.5,
                    "meta_adaptation_mult": 0.65,
                }
            }
            fields = self.mod.pmo_trade_journal_quality_fields(
                "SPY",
                {
                    "side": "LONG",
                    "entry_price": "100",
                    "exit_price": "106",
                    "entry_timestamp": "2026-06-17T09:45:00-04:00",
                    "exit_timestamp": "2026-06-17T10:30:00-04:00",
                },
                {},
                use_live_context=True,
            )
        finally:
            self.mod.pmo_deep_intelligence_report = original_report
        self.assertEqual(fields["deep_exit_policy"], "LET_WINNERS_WORK")
        self.assertEqual(fields["deep_attention_signal"], "NEUTRAL_ATTENTION")
        self.assertEqual(fields["deep_bayesian_confidence"], "LOW")

    def test_control_deck_injects_deep_intelligence_panel(self):
        html = (
            ".const-wrap{position:relative;height:215px}\n"
            "<svg class=\"csvg\" viewBox=\"0 0 570 215\"></svg>\n"
            "<div class=\"star-node\" style=\"left:266px;top:3px\" onclick=\"aiNodeInfo('agent')\"><div class=\"sc s-green\" style=\"width:31px;height:31px;font-size:13px\" id=\"cn-agent\">PLAN</div><div class=\"sl\" style=\"color:var(--green)\">Agent Plan</div></div>\n"
            "  const whynot=engineMap.whynot?!!engineMap.whynot.active:!!s.ENABLE_PMO_WHY_NOT_ENGINE;\n"
            "  const agent=engineMap.agent?!!engineMap.agent.active:!!s.ENABLE_PMO_ARCHITECTURE_PLANNER;\n"
            "  nodeState('whynot',whynot?'amber':'dim');\n"
            "    : [quantum,learning,warp,asi,signal,watchlist,sector,v112,whynot,agent].filter(Boolean).length;\n"
            "  const total=Number.isFinite(Number(constellation.total))?Number(constellation.total):10;\n"
            "    whynot:['Why-Not Engine','Records every blocked signal with reason.',[['ENABLE_PMO_WHY_NOT_ENGINE',S('ENABLE_PMO_WHY_NOT_ENGINE'),'var(--amber)'],['Min score',S('PMO_WHY_NOT_MIN_SCORE'),'var(--text2)'],['Min RVOL',S('PMO_WHY_NOT_MIN_RVOL'),'var(--text2)'],['Record audit',S('PMO_WHY_NOT_RECORD_AUDIT'),'var(--text2)']]],\n"
            "<div class=\"ca\" onclick=\"apiCmd('POST','/api/learning/refresh',{},'Refresh Learning Memory','')\"></div>\n"
            "    <div class=\"ca\" onclick=\"apiCmd('POST','/api/v113/asi/report',{},'Export ASI Report','')\"></div>"
        )
        updated = self.mod.pmo_deep_intelligence_deck_html(html)
        self.assertIn("deepIntelligencePanel", updated)
        self.assertIn("PMO Deep Intelligence", updated)
        self.assertIn("cn-deep", updated)
        self.assertIn("cn-frontier", updated)
        self.assertIn("cn-ensemble", updated)
        self.assertIn("engineMap.deep", updated)
        self.assertIn("engineMap.frontier", updated)
        self.assertIn("engineMap.advanced_ml", updated)
        self.assertIn("engineMap.meta_strategy", updated)
        self.assertIn("engineMap.vault", updated)
        self.assertIn("frontierIntelligencePanel", updated)
        self.assertIn("Number(constellation.total):20", updated)
        self.assertEqual(updated.count("deepIntelligencePanel"), 1)
        self.assertEqual(updated.count("cn-deep"), 1)
        self.assertEqual(updated.count("frontierIntelligencePanel"), 1)
        self.assertEqual(updated.count("cn-frontier"), 1)
        self.assertEqual(updated.count("cn-advanced_ml"), 1)
        self.assertEqual(updated.count("cn-meta_strategy"), 1)
        self.assertEqual(updated.count("cn-vault"), 1)
        self.assertEqual(self.mod.pmo_deep_intelligence_deck_html(updated).count("deepIntelligencePanel"), 1)
        self.assertEqual(self.mod.pmo_deep_intelligence_deck_html(updated).count("cn-deep"), 1)
        self.assertEqual(self.mod.pmo_deep_intelligence_deck_html(updated).count("frontierIntelligencePanel"), 1)
        self.assertEqual(self.mod.pmo_deep_intelligence_deck_html(updated).count("cn-frontier"), 1)
        self.assertEqual(self.mod.pmo_deep_intelligence_deck_html(updated).count("cn-advanced_ml"), 1)
        self.assertEqual(self.mod.pmo_deep_intelligence_deck_html(updated).count("cn-meta_strategy"), 1)
        self.assertEqual(self.mod.pmo_deep_intelligence_deck_html(updated).count("cn-vault"), 1)

    def test_tracked_orbital_deck_renders_all_twenty_constellation_nodes(self):
        html = (self.mod.PMO_DIR / "deck" / "pmo_orbital_command_deck.html").read_text(encoding="utf-8")
        for token in (
            "cn-quantum",
            "cn-learning",
            "cn-warp",
            "cn-asi",
            "cn-signal",
            "cn-watchlist",
            "cn-sector",
            "cn-v112",
            "cn-whynot",
            "cn-ensemble",
            "cn-alpha",
            "cn-institutional",
            "cn-deep",
            "cn-frontier",
            "cn-advanced_ml",
            "cn-meta_strategy",
            "cn-vault",
            "cn-crypto",
            "cn-postgate",
            "cn-agent",
        ):
            self.assertEqual(html.count(token), 1, token)
        self.assertIn("Number(constellation.total))?Number(constellation.total):20", html)
        self.assertIn("advanced_ml:['Advanced ML Intelligence'", html)
        self.assertIn("meta_strategy:['Meta Strategy / CFR'", html)
        self.assertIn("vault:['Vault Intelligence'", html)

    def test_trade_discipline_blocks_trend_entry_after_three_thirty(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "PMO_DISCIPLINE_MIN_CONFIRMATIONS": 0,
            "PMO_WHY_NOT_REQUIRE_RVOL": False,
            "ENABLE_PMO_STRATEGY_KNOWLEDGE_PACK": False,
        })
        report = self.mod.pmo_trade_discipline_check(
            {
                "symbol": "SPY",
                "score": 90,
                "relative_volume": 2.4,
                "bias": "CALL_BIAS",
                "change_pct": 1.1,
                "time": "15:35",
                "notional": 20,
            },
            settings,
            regime={"regime": "BULLISH", "risk_multiplier": 1.0},
            vwap_check={"status": "PASS"},
        )
        self.assertEqual(report["status"], "BLOCK")
        self.assertTrue(any("3:30 effect blocks trend-direction entry" in item for item in report["blockers"]))
        self.assertFalse(report["live_order_allowed"])

    def test_elite_signals_api_is_read_only(self):
        response = self.client.post(
            "/api/elite-signals",
            json={
                "symbol": "SPY",
                "direction": "long",
                "candidate": {"edge_signal": "BULLISH", "relative_volume": 2.1},
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()["elite_signals"]
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["orders_placed"])
        self.assertFalse(payload["live_unlocked"])

    def test_ratio_context_filter_is_not_a_trade_verdict(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "ENABLE_PMO_TRADE_DISCIPLINE_CHECKS": True,
            "ENABLE_PMO_DISCIPLINE_WHY_NOT_BLOCKERS": True,
            "PMO_DISCIPLINE_MIN_CONFIRMATIONS": 2,
            "PMO_WHY_NOT_MIN_SCORE": 78,
            "PMO_WHY_NOT_MIN_RVOL": 1.5,
        })
        result = self.mod.pmo_trade_discipline_check(
            {
                "symbol": "AAPL",
                "score": 88,
                "relative_volume": 2.0,
                "bias": "LONG",
                "notional": 40,
                "pe_ratio": 22.4,
            },
            settings,
            regime={"regime": "BULLISH", "risk_multiplier": 1.0},
        )
        self.assertEqual(result["ratio_context"]["status"], "RATIO_ONLY")
        self.assertTrue(any("ratios present without cash-flow" in item for item in result["warnings"]))
        self.assertFalse(any("ratio" in item.lower() for item in result["blockers"]))
        self.assertFalse(result["live_order_allowed"])

    def test_backtest_simulator_is_research_only_with_synthetic_rows(self):
        rows = []
        price = 100.0
        for idx in range(80):
            price += 0.8
            rows.append({
                "date": f"2026-06-12 10:{idx:02d}",
                "open": price - 0.2,
                "high": price * 1.02,
                "low": price * 0.995,
                "close": price,
                "volume": 1000 + idx * 10,
            })
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "ENABLE_PMO_BACKTEST_SIMULATOR": True,
            "PMO_BACKTEST_DEFAULT_SYMBOLS": ["TEST"],
            "PMO_BACKTEST_MIN_INTRADAY_ROWS": 20,
            "PMO_BACKTEST_LOOKAHEAD_BARS": 6,
            "PMO_DEFAULT_STOP_LOSS_PCT": 4.0,
            "PMO_DEFAULT_TAKE_PROFIT_PCT": 3.0,
        })
        result = self.mod.pmo_backtest_simulator(settings, symbols=["TEST"], rows_by_symbol={"TEST": rows}, record=False)
        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "RESEARCH_ONLY_BACKTEST")
        self.assertFalse(result["live_order_allowed"])
        self.assertGreater(result["summary"]["trades"], 0)

    def test_backtest_record_post_requires_admin_token(self):
        response = self.client.post("/api/backtest/run", json={"record": True})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.get_json()["locked"])

    def test_learning_constellation_counts_all_safe_engines(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "ENABLE_PMO_QUANTUM_LEARNING_MATRIX": True,
            "ENABLE_PMO_LEARNING_ENGINE": True,
            "ENABLE_PMO_WARP_ENGINE": True,
            "ENABLE_PMO_ASI_LEARNING": True,
            "ENABLE_TRADINGVIEW_WEBHOOK_BRIDGE": True,
            "ENABLE_PMO_AUTO_WATCHLIST_AI": True,
            "ENABLE_SECTOR_ROTATION_MOMENTUM_AI": True,
            "ENABLE_PMO_V112_PAPER_REPLAY_JOURNAL": True,
            "ENABLE_PMO_WHY_NOT_ENGINE": True,
            "ENABLE_PMO_ENSEMBLE_VOTING": True,
            "PMO_ALPHA_DECAY_ENABLED": True,
            "ENABLE_PMO_INSTITUTIONAL_SIGNALS": True,
            "ENABLE_PMO_DEEP_INTELLIGENCE": True,
            "ENABLE_PMO_FRONTIER_INTELLIGENCE": True,
            "ENABLE_PMO_META_STRATEGY_LAYER": True,
            "ENABLE_PMO_VAULT_INTELLIGENCE": True,
            "PMO_CRYPTO_PROFILE_ENABLED": True,
            "ENABLE_PMO_POST_GATE_EQUITY_PROOF": True,
            "ENABLE_PMO_ARCHITECTURE_PLANNER": True,
            "PMO_ASI_ALLOW_LIVE_INFLUENCE": False,
            "PMO_AI_WARP_ENABLED": False,
        })
        result = self.mod.pmo_learning_constellation_status(settings)
        engine_ids = {row["id"] for row in result["engines"]}
        self.assertEqual(result["total"], 20)
        self.assertGreaterEqual(result["active_count"], 10)
        self.assertTrue({"ensemble", "alpha", "institutional", "deep", "frontier", "advanced_ml", "meta_strategy", "vault", "crypto", "postgate"}.issubset(engine_ids))
        self.assertTrue(result["live_influence_locked"])
        self.assertFalse(result["passive_provider_calls"])

    def test_dashboard_paper_approval_requires_admin_token(self):
        response = self.client.post(
            "/api/dashboard/paper-trade/approve",
            json={"row": {"symbol": "SPY", "score": 90, "bias": "LONG"}, "confirm_phrase": "PMO APPROVE PAPER"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.get_json()["locked"])

    def test_dashboard_paper_approval_never_allows_live(self):
        settings = dict(self.mod.DEFAULT_SETTINGS)
        settings.update({
            "ALPACA_PAPER": False,
            "PMO_ALLOW_LIVE_TRADING": True,
            "PMO_LIVE_TRADING_ENABLED": True,
            "PMO_ORDER_EXECUTION_MODE": "LIVE_ALPACA",
        })
        result = self.mod.pmo_dashboard_paper_trade_approval(
            {
                "row": {"symbol": "SPY", "score": 90, "bias": "LONG", "notional": 25},
                "confirm_phrase": "PMO APPROVE PAPER",
            },
            settings,
        )
        self.assertTrue(result["ok"])
        self.assertFalse(result["submitted"])
        self.assertFalse(result["approval"]["live_order_allowed"])
        self.assertTrue(any("PAPER_ALPACA" in item for item in result["approval"]["blocked"]))

    def test_firewall_status_route_is_read_only(self):
        bot = self.mod.bot
        original_account_snapshot = bot.account_snapshot
        original_connection_check = bot.connection_check
        original_market_regime = bot.market_regime
        try:
            bot.account_snapshot = lambda: {
                "ok": True,
                "equity": 200,
                "buying_power": 200,
                "trading_blocked": False,
                "account_blocked": False,
            }
            bot.connection_check = lambda: {"online": 3, "total": 3, "connections": []}
            bot.connection_health = {"online": 3, "total": 3, "connections": []}
            bot.market_regime = lambda: {"regime": "BULLISH", "risk_multiplier": 1.0}
            response = self.client.get("/api/firewall/status")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["firewall"]["live_order_allowed"])
        finally:
            bot.account_snapshot = original_account_snapshot
            bot.connection_check = original_connection_check
            bot.market_regime = original_market_regime

    def _run_executor_gate_test(self, settings, decision_overrides, open_orders=None, payload=None):
        bot = self.mod.bot
        original_settings = bot.settings
        original_account_snapshot = bot.account_snapshot
        original_connection_check = bot.connection_check
        original_market_regime = bot.market_regime
        original_trading_client = bot.trading_client
        original_open_positions = self.mod.open_positions
        original_open_orders = self.mod.open_orders_snapshot
        original_profile_open_positions = bot.open_positions_for_profile
        original_profile_open_orders = bot.open_orders_snapshot_for_profile
        original_paper_proof = self.mod.pmo_paper_proof_snapshot
        original_order_file = self.mod.PMO_ORDER_EXECUTION_FILE
        try:
            with tempfile.TemporaryDirectory() as tmp:
                self.mod.PMO_ORDER_EXECUTION_FILE = Path(tmp) / "pmo_order_execution.csv"
                bot.settings = settings
                bot.trading_client = None
                bot.account_snapshot = lambda: {
                    "ok": True,
                    "status": "ACTIVE",
                    "equity": 200,
                    "buying_power": 200,
                    "cash": 200,
                    "day_pnl": 0,
                    "day_pnl_percent": 0,
                    "trading_blocked": False,
                    "account_blocked": False,
                }
                bot.connection_check = lambda: {"online": 10, "total": 10, "connections": []}
                bot.market_regime = lambda: {"regime": "BULLISH", "risk_multiplier": 1.0, "volatility_pressure": False}
                self.mod.open_positions = lambda: []
                self.mod.open_orders_snapshot = lambda: list(open_orders or [])
                bot.open_positions_for_profile = lambda profile=None, client=None: []
                bot.open_orders_snapshot_for_profile = lambda profile=None, client=None: list(open_orders or [])
                self.mod.pmo_paper_proof_snapshot = lambda settings=None, record=False: {"ready_to_unlock_live": False, "score": 0, "status": "PROOF BUILDING"}
                decision = {
                    "symbol": "SPY",
                    "side": "LONG",
                    "score": 90,
                    "market_data": {"ok": True, "price": 100},
                }
                decision.update(decision_overrides)
                return bot.submit_order_from_decision(decision, payload or {"price": 100, "notional": 10})
        finally:
            bot.settings = original_settings
            bot.account_snapshot = original_account_snapshot
            bot.connection_check = original_connection_check
            bot.market_regime = original_market_regime
            bot.trading_client = original_trading_client
            self.mod.open_positions = original_open_positions
            self.mod.open_orders_snapshot = original_open_orders
            bot.open_positions_for_profile = original_profile_open_positions
            bot.open_orders_snapshot_for_profile = original_profile_open_orders
            self.mod.pmo_paper_proof_snapshot = original_paper_proof
            self.mod.PMO_ORDER_EXECUTION_FILE = original_order_file


if __name__ == "__main__":
    unittest.main()
