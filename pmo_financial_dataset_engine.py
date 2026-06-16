from __future__ import annotations

import csv
import json
import math
import random
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DATASET_NAME = "PMO Synthetic Banking Lending Payments Dataset"
DATASET_VERSION = "v1.0"
ACCOUNT_TYPES = ("CHECKING", "SAVINGS", "CREDIT_CARD", "INSTALLMENT_LOAN", "MERCHANT_SETTLEMENT")
CHANNELS = ("ACH", "CARD", "WIRE", "ATM", "BILL_PAY", "P2P", "MERCHANT", "LOAN")
TRADING_VENUES = ("NYSE", "NASDAQ", "ARCA", "IEX", "CBOE", "DARK_POOL_A", "RFQ_PLATFORM_A")
EXECUTION_STRATEGIES = ("VWAP", "TWAP", "POV", "IS", "MANUAL", "RFQ", "DARK_LIQUIDITY")
TCA_DIMENSIONS = ("trader_id", "desk_id", "venue", "strategy", "period", "entity_id")
TCA_METRICS = (
    "slippage_bps",
    "market_impact_bps",
    "timing_cost_bps",
    "opportunity_cost_bps",
    "arrival_cost_bps",
    "fill_rate",
)
BACKTEST_HORIZONS = ("EOD", "INTRADAY_BAR", "TICK")
MARKET_STRESS_PERIODS = ("COVID_LIQUIDITY_SHOCK", "RATE_HIKE_VOLATILITY", "BANKING_STRESS", "MEME_STOCK_VOLATILITY", "NORMAL_SESSION")
LIFECYCLE_STAGES = (
    "ONBOARDING",
    "ACTIVE",
    "CREDIT_APPLICATION",
    "DISBURSEMENT",
    "REPAYMENT",
    "DELINQUENCY",
    "CURE",
    "CHARGEOFF",
    "DISPUTE",
    "CLOSURE",
)
RISK_TIERS = ("LOW", "MEDIUM", "ELEVATED", "HIGH")


def _now_iso() -> str:
    return datetime.now().isoformat()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _append_manifest(path: Path, row: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists() and path.stat().st_size > 0
    fieldnames = [
        "timestamp",
        "package_id",
        "mode",
        "target_rows",
        "client_rows",
        "account_rows",
        "transaction_rows",
        "dataset_dir",
        "validation_status",
        "documentation_file",
        "audit_package_file",
    ]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({key: row.get(key, "") for key in fieldnames})


def finance_dataset_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    target_rows = max(1_000_000, _safe_int(settings.get("PMO_FINANCE_DATASET_TARGET_ROWS"), 1_000_000))
    return {
        "enabled": bool(settings.get("ENABLE_PMO_FINANCIAL_DATASET_LAB", True)),
        "synthetic_only": bool(settings.get("PMO_FINANCE_DATASET_SYNTHETIC_ONLY", True)),
        "target_rows": target_rows,
        "default_sample_rows": max(100, _safe_int(settings.get("PMO_FINANCE_DATASET_DEFAULT_SAMPLE_ROWS"), 2500)),
        "max_generate_rows": max(10_000, _safe_int(settings.get("PMO_FINANCE_DATASET_MAX_GENERATE_ROWS"), target_rows)),
    }


def domain_rules() -> List[Dict[str, Any]]:
    return [
        {"id": "KYC_REQUIRED", "domain": "banking", "severity": "critical", "rule": "Every client must have KYC status before account activation."},
        {"id": "AML_VELOCITY", "domain": "payments", "severity": "high", "rule": "Payment velocity, round-dollar bursts, and cross-border wires require review flags."},
        {"id": "NSF_TRACKING", "domain": "banking", "severity": "high", "rule": "Checking accounts must track negative balance windows and NSF events."},
        {"id": "DTI_LIMIT", "domain": "lending", "severity": "high", "rule": "Loan origination must enforce debt-to-income and risk-tier limits."},
        {"id": "CREDIT_UTILIZATION", "domain": "lending", "severity": "medium", "rule": "Credit utilization above 80 percent must raise risk pressure."},
        {"id": "ACH_RETURN_CODES", "domain": "payments", "severity": "medium", "rule": "ACH returns must carry a reason code and lifecycle event."},
        {"id": "CARD_DISPUTE_WINDOW", "domain": "payments", "severity": "medium", "rule": "Card disputes and chargebacks must link to the original transaction."},
        {"id": "SETTLEMENT_TIMING", "domain": "payments", "severity": "medium", "rule": "Merchant settlement follows channel-specific lag and reconciliation status."},
        {"id": "CHARGEOFF_LIFECYCLE", "domain": "lending", "severity": "critical", "rule": "Chargeoff can occur only after delinquency history exists."},
        {"id": "SYNTHETIC_PII_ONLY", "domain": "governance", "severity": "critical", "rule": "Dataset must use synthetic identifiers only and must not store real bank credentials or PII."},
    ]


def institution_constraints() -> List[Dict[str, Any]]:
    return [
        {"area": "retail_bank", "constraint": "Deposit accounts require KYC_PASS or KYC_REVIEW status before ACTIVE lifecycle."},
        {"area": "credit_union", "constraint": "Membership date must precede account open date and loan application date."},
        {"area": "lender", "constraint": "HIGH risk tier cannot exceed configured installment loan exposure cap without manual review."},
        {"area": "payments_processor", "constraint": "Merchant settlement account cannot receive non-merchant channel transactions."},
        {"area": "card_program", "constraint": "Card authorization, clearing, dispute, and chargeback events must preserve trace ids."},
        {"area": "audit", "constraint": "All generated files include a package id, timestamp, row counts, and synthetic-only attestation."},
    ]


def tca_repository_tables() -> List[Dict[str, Any]]:
    return [
        {"table": "parent_orders", "grain": "portfolio order", "fields": "parent_order_id, portfolio_id, trader_id, desk_id, strategy, side, symbol, target_qty, arrival_price, decision_time, benchmark_price"},
        {"table": "child_orders", "grain": "routed order slice", "fields": "child_order_id, parent_order_id, venue, algo_name, route_time, order_qty, limit_price, time_in_force"},
        {"table": "algo_executions", "grain": "algo event", "fields": "algo_event_id, child_order_id, algo_name, event_time, participation_rate, urgency, state"},
        {"table": "rfqs", "grain": "RFQ quote", "fields": "rfq_id, parent_order_id, counterparty, quote_price, quote_qty, quote_time, accepted"},
        {"table": "axes", "grain": "liquidity indication", "fields": "axis_id, venue, counterparty, symbol, side, size, price, valid_until"},
        {"table": "fills", "grain": "individual fill", "fields": "fill_id, child_order_id, fill_time, fill_qty, fill_price, venue, liquidity_flag, fee"},
        {"table": "market_data", "grain": "quote/trade snapshot", "fields": "symbol, timestamp, bid, ask, mid, last, volume, volatility"},
        {"table": "tca_metrics", "grain": "metric observation", "fields": "entity_type, entity_id, slippage_bps, market_impact_bps, timing_cost_bps, opportunity_cost_bps, arrival_cost_bps"},
        {"table": "best_execution_evidence", "grain": "audit evidence", "fields": "evidence_id, parent_order_id, policy_check, result, detail, timestamp, reviewer"},
    ]


def tca_metric_definitions() -> List[Dict[str, Any]]:
    return [
        {"metric": "slippage_bps", "definition": "Execution price versus selected benchmark, normalized in basis points."},
        {"metric": "market_impact_bps", "definition": "Estimated adverse movement attributable to order participation and venue footprint."},
        {"metric": "timing_cost_bps", "definition": "Cost from decision time to order release or route time."},
        {"metric": "opportunity_cost_bps", "definition": "Unfilled quantity cost versus benchmark when the market moves away."},
        {"metric": "arrival_cost_bps", "definition": "Implementation shortfall from arrival price through final fill."},
        {"metric": "venue_quality_score", "definition": "Composite venue score using fill rate, spread capture, fees, adverse selection, and reject rate."},
    ]


def mifid_best_execution_controls() -> List[Dict[str, Any]]:
    return [
        {"control": "RTS_28_VENUE_ANALYSIS", "purpose": "Show venue quality by instrument, trader, desk, strategy, and period."},
        {"control": "ORDER_LIFECYCLE_RECON", "purpose": "Link parent orders, child orders, algo events, RFQs, axes, fills, and market data."},
        {"control": "NO_PRE_AGG_LIMIT", "purpose": "Store granular fills and market data so analytics can drill down without losing history."},
        {"control": "BEST_EXECUTION_POLICY_CHECK", "purpose": "Document why route/venue/strategy selection satisfied execution policy."},
        {"control": "AUDIT_TRAIL_IMMUTABILITY", "purpose": "Preserve timestamps, source systems, evidence ids, and reviewer notes."},
        {"control": "REAL_TIME_EXCEPTION_MONITOR", "purpose": "Flag slippage, opportunity cost, venue rejects, RFQ misses, and timing cost while orders are active."},
    ]


def pre_trade_intelligence_capabilities() -> List[Dict[str, Any]]:
    return [
        {"capability": "market_impact_prediction", "description": "Estimate expected market impact before order release using historical fill, venue, strategy, volatility, and participation patterns."},
        {"capability": "venue_recommendation", "description": "Rank venues and counterparties by expected slippage, fill rate, market impact, and opportunity cost."},
        {"capability": "strategy_simulation", "description": "Compare VWAP, TWAP, POV, IS, RFQ, manual, and dark-liquidity execution outcomes before trading."},
        {"capability": "what_if_scenarios", "description": "Change order size, timing, venue, urgency, and strategy to estimate transaction-cost sensitivity."},
        {"capability": "cost_forecast", "description": "Forecast slippage, timing cost, opportunity cost, market impact, and arrival cost in basis points."},
    ]


def governed_market_data_capabilities() -> List[Dict[str, Any]]:
    return [
        {"capability": "eod_intraday_tick_store", "description": "Single governed store for EOD, intraday bar, and tick-style research data."},
        {"capability": "industrialized_backtesting", "description": "Run daily, bar, or tick-based backtests without changing tools or switching databases."},
        {"capability": "stress_replay", "description": "Replay historical stress periods with reproducible assumptions and fixed data snapshots."},
        {"capability": "versioned_snapshots", "description": "Attach backtest results to a named market-data snapshot such as official close of that day."},
        {"capability": "institution_extensions", "description": "Start from tested patterns and extend with desk, venue, counterparty, or mandate-specific rules."},
        {"capability": "automated_quality_checks", "description": "Validate completeness, bid/ask sanity, stale timestamps, duplicates, outliers, and cross-source consistency."},
        {"capability": "columnar_time_partitioning", "description": "Model data by source, asset class, symbol, date, and horizon for fast ad-hoc analytics."},
        {"capability": "explainable_lineage", "description": "Expose source, snapshot, partition, quality rule, correction, and derived-metric lineage."},
    ]


def market_data_quality_rules() -> List[Dict[str, Any]]:
    return [
        {"id": "MD_REQUIRED_FIELDS", "severity": "critical", "check": "symbol, timestamp, bid, ask, mid, last, volume, and volatility must be present."},
        {"id": "MD_BID_ASK_SANITY", "severity": "critical", "check": "bid must be less than or equal to ask; spread must be non-negative."},
        {"id": "MD_MID_CONSISTENCY", "severity": "high", "check": "mid should equal bid/ask midpoint within tolerance."},
        {"id": "MD_STALE_TIMESTAMP", "severity": "medium", "check": "timestamps must fit the expected EOD/intraday/tick horizon."},
        {"id": "MD_DUPLICATE_SNAPSHOT", "severity": "medium", "check": "symbol and timestamp duplicate rows require reconciliation."},
        {"id": "MD_VOLUME_COMPLETENESS", "severity": "medium", "check": "volume must be non-negative and populated for VWAP/liquidity analytics."},
        {"id": "MD_OUTLIER_SPREAD", "severity": "medium", "check": "spread and volatility outliers are flagged for review."},
        {"id": "MD_CROSS_SOURCE_RECON", "severity": "high", "check": "source A and source B prices must reconcile within configured tolerance."},
    ]


def market_data_model() -> Dict[str, Any]:
    return {
        "store_type": "columnar_time_partitioned_model",
        "partitions": ["asset_class", "symbol", "date", "horizon", "source", "snapshot_version"],
        "tables": {
            "market_data": ["symbol", "timestamp", "bid", "ask", "mid", "last", "volume", "volatility", "source", "snapshot_version"],
            "market_data_quality_events": ["event_id", "rule_id", "severity", "symbol", "timestamp", "field", "observed", "expected", "explanation"],
            "market_data_adjustments": ["adjustment_id", "snapshot_version", "symbol", "timestamp", "field", "old_value", "new_value", "reason", "owner"],
            "market_data_snapshots": ["snapshot_version", "as_of", "horizon", "source_count", "row_count", "quality_status"],
        },
        "ingestion_safeguards": [
            "schema validation before write",
            "atomic landing to curated promotion",
            "source freshness checks",
            "duplicate key quarantine",
            "cross-source reconciliation before trusted flag",
            "immutable snapshot id for reproducibility",
        ],
        "derived_metrics": ["rolling_vwap", "spread_bps", "liquidity_score", "realized_volatility", "return_correlation", "curve_slope"],
    }


def _risk_tier(score: int) -> str:
    if score >= 760:
        return "LOW"
    if score >= 680:
        return "MEDIUM"
    if score >= 600:
        return "ELEVATED"
    return "HIGH"


def _client_row(idx: int, rng: random.Random, start_date: datetime) -> Dict[str, Any]:
    credit_score = rng.randint(520, 820)
    income = rng.randint(28000, 240000)
    risk = _risk_tier(credit_score)
    onboarded = start_date + timedelta(days=rng.randint(0, 900))
    kyc = "KYC_PASS" if rng.random() > 0.04 else "KYC_REVIEW"
    return {
        "client_id": f"CL{idx:08d}",
        "segment": rng.choice(("RETAIL", "SMB", "PREMIER", "STUDENT")),
        "synthetic_name": f"Synthetic Client {idx:08d}",
        "kyc_status": kyc,
        "risk_tier": risk,
        "credit_score": credit_score,
        "annual_income": income,
        "debt_to_income": round(rng.uniform(0.05, 0.62), 3),
        "onboarded_at": onboarded.date().isoformat(),
        "lifecycle_stage": "ACTIVE" if kyc == "KYC_PASS" else "ONBOARDING",
        "state": rng.choice(("CA", "TX", "NY", "FL", "GA", "IL", "NC", "AZ", "WA", "MI")),
    }


def _account_rows_for_client(client: Dict[str, Any], rng: random.Random, max_accounts: int = 4) -> List[Dict[str, Any]]:
    count = rng.randint(1, max_accounts)
    rows: List[Dict[str, Any]] = []
    opened_base = datetime.fromisoformat(str(client["onboarded_at"]))
    for seq in range(count):
        account_type = ACCOUNT_TYPES[min(seq, len(ACCOUNT_TYPES) - 1)] if seq < 2 else rng.choice(ACCOUNT_TYPES)
        opened = opened_base + timedelta(days=rng.randint(0, 180))
        limit = 0
        if account_type == "CREDIT_CARD":
            limit = rng.choice((500, 1000, 2500, 5000, 10000, 15000))
        elif account_type == "INSTALLMENT_LOAN":
            limit = rng.choice((2500, 5000, 10000, 20000, 35000))
        rows.append({
            "account_id": f"AC{client['client_id'][2:]}{seq:02d}",
            "client_id": client["client_id"],
            "account_type": account_type,
            "opened_at": opened.date().isoformat(),
            "status": "ACTIVE" if client["kyc_status"] == "KYC_PASS" else "PENDING_KYC",
            "credit_limit": limit,
            "interest_rate": round(rng.uniform(0.01, 0.299), 4) if account_type in {"CREDIT_CARD", "INSTALLMENT_LOAN"} else 0,
            "institution_program": rng.choice(("RETAIL_BANK", "CREDIT_UNION", "CARD_PROGRAM", "PAYMENTS_PROCESSOR")),
        })
    return rows


def _transaction_row(idx: int, account: Dict[str, Any], client: Dict[str, Any], rng: random.Random, start_date: datetime) -> Dict[str, Any]:
    channel = rng.choice(CHANNELS)
    account_type = str(account["account_type"])
    days = rng.randint(0, 1095)
    ts = start_date + timedelta(days=days, minutes=rng.randint(0, 1439))
    base_amount = rng.lognormvariate(3.3, 1.0)
    sign = -1 if channel in {"CARD", "ATM", "BILL_PAY", "P2P"} and rng.random() > 0.18 else 1
    if account_type in {"CREDIT_CARD", "INSTALLMENT_LOAN"} and channel == "REPAYMENT":
        sign = 1
    amount = round(sign * min(base_amount, 25000), 2)
    fraud_pressure = 0.0
    if str(client["risk_tier"]) in {"ELEVATED", "HIGH"}:
        fraud_pressure += 0.08
    if abs(amount) > 5000:
        fraud_pressure += 0.05
    if channel in {"WIRE", "P2P"}:
        fraud_pressure += 0.04
    dispute = channel in {"CARD", "MERCHANT"} and rng.random() < (0.006 + fraud_pressure / 10)
    ach_return = channel == "ACH" and rng.random() < (0.012 if client["risk_tier"] == "HIGH" else 0.004)
    delinquency = account_type in {"CREDIT_CARD", "INSTALLMENT_LOAN"} and rng.random() < (0.025 if client["risk_tier"] in {"ELEVATED", "HIGH"} else 0.006)
    lifecycle = "ACTIVE"
    if delinquency:
        lifecycle = rng.choice(("DELINQUENCY", "CURE", "CHARGEOFF"))
    elif dispute:
        lifecycle = "DISPUTE"
    elif account_type == "INSTALLMENT_LOAN" and channel == "LOAN":
        lifecycle = rng.choice(("DISBURSEMENT", "REPAYMENT"))
    return {
        "transaction_id": f"TX{idx:012d}",
        "account_id": account["account_id"],
        "client_id": client["client_id"],
        "posted_at": ts.isoformat(),
        "channel": channel,
        "amount": amount,
        "currency": "USD",
        "lifecycle_stage": lifecycle,
        "risk_tier_at_event": client["risk_tier"],
        "fraud_score": round(min(0.99, rng.random() * 0.35 + fraud_pressure), 3),
        "dispute_flag": dispute,
        "ach_return_code": rng.choice(("R01", "R02", "R03", "R10")) if ach_return else "",
        "delinquency_bucket": rng.choice(("30", "60", "90", "120")) if delinquency else "0",
        "trace_id": f"TRACE{idx:012d}",
    }


def _tca_sample(order_count: int, rng: random.Random, start_date: datetime) -> Dict[str, List[Dict[str, Any]]]:
    symbols = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMD", "META", "JPM", "XLF", "XLK")
    parent_orders: List[Dict[str, Any]] = []
    child_orders: List[Dict[str, Any]] = []
    algo_executions: List[Dict[str, Any]] = []
    rfqs: List[Dict[str, Any]] = []
    axes: List[Dict[str, Any]] = []
    fills: List[Dict[str, Any]] = []
    market_data: List[Dict[str, Any]] = []
    tca_metrics: List[Dict[str, Any]] = []
    best_execution: List[Dict[str, Any]] = []
    fill_idx = 1
    child_idx = 1
    event_idx = 1
    for idx in range(1, order_count + 1):
        symbol = rng.choice(symbols)
        side = rng.choice(("BUY", "SELL"))
        target_qty = rng.choice((100, 250, 500, 1000, 2500, 5000))
        arrival = round(rng.uniform(20, 700), 4)
        benchmark = round(arrival * (1 + rng.uniform(-0.004, 0.004)), 4)
        decision_time = start_date + timedelta(days=rng.randint(0, 260), minutes=rng.randint(570, 960))
        strategy = rng.choice(EXECUTION_STRATEGIES)
        parent_id = f"PO{idx:010d}"
        parent_orders.append({
            "parent_order_id": parent_id,
            "portfolio_id": f"PF{rng.randint(1, 25):03d}",
            "trader_id": f"TR{rng.randint(1, 50):03d}",
            "desk_id": rng.choice(("EQUITY", "ETF", "PROGRAM", "CASH", "RFQ")),
            "strategy": strategy,
            "side": side,
            "symbol": symbol,
            "target_qty": target_qty,
            "arrival_price": arrival,
            "decision_time": decision_time.isoformat(),
            "benchmark_price": benchmark,
            "source_system": rng.choice(("OMS_A", "EMS_B", "TCA_VENDOR_C", "VENUE_DROP_COPY")),
        })
        child_count = rng.randint(1, 5)
        remaining = target_qty
        parent_fill_qty = 0
        parent_notional = 0.0
        for cseq in range(child_count):
            qty = remaining if cseq == child_count - 1 else max(1, int(target_qty / child_count * rng.uniform(0.7, 1.3)))
            remaining = max(0, remaining - qty)
            venue = rng.choice(TRADING_VENUES)
            child_id = f"CO{child_idx:010d}"
            child_idx += 1
            route_time = decision_time + timedelta(minutes=rng.randint(0, 120))
            child_orders.append({
                "child_order_id": child_id,
                "parent_order_id": parent_id,
                "venue": venue,
                "algo_name": strategy,
                "route_time": route_time.isoformat(),
                "order_qty": qty,
                "limit_price": round(arrival * (1 + rng.uniform(-0.006, 0.006)), 4),
                "time_in_force": rng.choice(("DAY", "IOC", "FOK", "GTD")),
            })
            algo_executions.append({
                "algo_event_id": f"AE{event_idx:010d}",
                "child_order_id": child_id,
                "algo_name": strategy,
                "event_time": route_time.isoformat(),
                "participation_rate": round(rng.uniform(0.02, 0.25), 3),
                "urgency": rng.choice(("LOW", "NORMAL", "HIGH")),
                "state": rng.choice(("STARTED", "ROUTING", "THROTTLED", "COMPLETED")),
            })
            event_idx += 1
            fill_count = rng.randint(1, 4)
            for _ in range(fill_count):
                fill_qty = max(1, int(qty / fill_count * rng.uniform(0.65, 1.1)))
                drift = rng.uniform(-0.006, 0.006)
                if side == "BUY":
                    fill_price = round(arrival * (1 + drift), 4)
                    slippage_bps = ((fill_price - benchmark) / benchmark) * 10000
                else:
                    fill_price = round(arrival * (1 - drift), 4)
                    slippage_bps = ((benchmark - fill_price) / benchmark) * 10000
                fill_time = route_time + timedelta(minutes=rng.randint(0, 90), seconds=rng.randint(0, 59))
                fee = round(abs(fill_qty * fill_price) * rng.uniform(0.00001, 0.00008), 4)
                fills.append({
                    "fill_id": f"FL{fill_idx:012d}",
                    "child_order_id": child_id,
                    "parent_order_id": parent_id,
                    "fill_time": fill_time.isoformat(),
                    "fill_qty": fill_qty,
                    "fill_price": fill_price,
                    "venue": venue,
                    "liquidity_flag": rng.choice(("ADD", "REMOVE", "AUCTION", "RFQ")),
                    "fee": fee,
                    "slippage_bps": round(slippage_bps, 3),
                })
                parent_fill_qty += fill_qty
                parent_notional += fill_qty * fill_price
                fill_idx += 1
            mid = round(arrival * (1 + rng.uniform(-0.008, 0.008)), 4)
            spread = max(0.01, mid * rng.uniform(0.00005, 0.0015))
            market_data.append({
                "symbol": symbol,
                "timestamp": route_time.isoformat(),
                "bid": round(mid - spread / 2, 4),
                "ask": round(mid + spread / 2, 4),
                "mid": mid,
                "last": round(mid * (1 + rng.uniform(-0.001, 0.001)), 4),
                "volume": rng.randint(50_000, 9_000_000),
                "volatility": round(rng.uniform(0.08, 0.65), 4),
            })
        if strategy == "RFQ":
            rfq_id = f"RFQ{idx:010d}"
            quote = round(arrival * (1 + rng.uniform(-0.004, 0.004)), 4)
            rfqs.append({
                "rfq_id": rfq_id,
                "parent_order_id": parent_id,
                "counterparty": f"CP{rng.randint(1, 20):03d}",
                "quote_price": quote,
                "quote_qty": target_qty,
                "quote_time": (decision_time + timedelta(minutes=1)).isoformat(),
                "accepted": rng.random() > 0.28,
            })
        if rng.random() < 0.35:
            axes.append({
                "axis_id": f"AX{idx:010d}",
                "venue": rng.choice(TRADING_VENUES),
                "counterparty": f"CP{rng.randint(1, 20):03d}",
                "symbol": symbol,
                "side": side,
                "size": rng.choice((1000, 2500, 5000, 10000)),
                "price": round(arrival * (1 + rng.uniform(-0.003, 0.003)), 4),
                "valid_until": (decision_time + timedelta(hours=2)).isoformat(),
            })
        avg_fill = parent_notional / parent_fill_qty if parent_fill_qty else arrival
        if side == "BUY":
            arrival_cost = ((avg_fill - arrival) / arrival) * 10000
        else:
            arrival_cost = ((arrival - avg_fill) / arrival) * 10000
        opportunity = max(0, (target_qty - parent_fill_qty) / max(target_qty, 1)) * abs(rng.uniform(1, 35))
        market_impact = abs(arrival_cost) * rng.uniform(0.15, 0.55)
        timing_cost = abs(((benchmark - arrival) / arrival) * 10000) * rng.uniform(0.4, 1.2)
        tca_metrics.append({
            "entity_type": "parent_order",
            "entity_id": parent_id,
            "trader_id": parent_orders[-1]["trader_id"],
            "desk_id": parent_orders[-1]["desk_id"],
            "venue": "MULTI" if child_count > 1 else child_orders[-1]["venue"],
            "strategy": strategy,
            "period": decision_time.date().isoformat(),
            "slippage_bps": round(arrival_cost, 3),
            "market_impact_bps": round(market_impact, 3),
            "timing_cost_bps": round(timing_cost, 3),
            "opportunity_cost_bps": round(opportunity, 3),
            "arrival_cost_bps": round(arrival_cost, 3),
            "fill_rate": round(parent_fill_qty / target_qty, 4),
        })
        best_execution.append({
            "evidence_id": f"BX{idx:010d}",
            "parent_order_id": parent_id,
            "policy_check": "MIFID_II_BEST_EXECUTION",
            "result": "PASS" if abs(arrival_cost) < 65 and opportunity < 25 else "REVIEW",
            "detail": "Route, venue, benchmark, slippage, market impact, timing cost, opportunity cost, and fill lineage preserved.",
            "timestamp": datetime.now().isoformat(),
            "reviewer": "PMO_SYNTHETIC_AUDIT",
        })
    return {
        "parent_orders": parent_orders,
        "child_orders": child_orders,
        "algo_executions": algo_executions,
        "rfqs": rfqs,
        "axes": axes,
        "fills": fills,
        "market_data": market_data,
        "tca_metrics": tca_metrics,
        "best_execution_evidence": best_execution,
    }


def _iter_sample(clients_count: int, accounts_target: int, transactions_count: int, seed: int = 206) -> Dict[str, List[Dict[str, Any]]]:
    rng = random.Random(seed)
    start_date = datetime.now() - timedelta(days=1095)
    clients = [_client_row(idx + 1, rng, start_date) for idx in range(clients_count)]
    accounts: List[Dict[str, Any]] = []
    for client in clients:
        accounts.extend(_account_rows_for_client(client, rng))
        if len(accounts) >= accounts_target:
            break
    if not accounts:
        accounts = _account_rows_for_client(clients[0], rng)
    transactions = []
    for idx in range(transactions_count):
        account = rng.choice(accounts)
        client = clients[int(account["client_id"][2:]) - 1]
        transactions.append(_transaction_row(idx + 1, account, client, rng, start_date))
    return {"clients": clients, "accounts": accounts[:accounts_target], "transactions": transactions}


def _write_table(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def validation_summary(sample: Dict[str, List[Dict[str, Any]]], target_rows: int) -> Dict[str, Any]:
    clients = sample.get("clients", [])
    accounts = sample.get("accounts", [])
    transactions = sample.get("transactions", [])
    client_ids = {row["client_id"] for row in clients}
    account_ids = {row["account_id"] for row in accounts}
    orphan_accounts = sum(1 for row in accounts if row["client_id"] not in client_ids)
    orphan_transactions = sum(1 for row in transactions if row["account_id"] not in account_ids or row["client_id"] not in client_ids)
    lifecycle_counts: Dict[str, int] = {}
    channel_counts: Dict[str, int] = {}
    high_risk_tx = 0
    dispute_count = 0
    ach_returns = 0
    delinquency_count = 0
    tca = sample.get("tca", {})
    tca_metrics = tca.get("tca_metrics", []) if isinstance(tca, dict) else []
    best_execution = tca.get("best_execution_evidence", []) if isinstance(tca, dict) else []
    for row in transactions:
        lifecycle_counts[str(row["lifecycle_stage"])] = lifecycle_counts.get(str(row["lifecycle_stage"]), 0) + 1
        channel_counts[str(row["channel"])] = channel_counts.get(str(row["channel"]), 0) + 1
        high_risk_tx += 1 if row["risk_tier_at_event"] == "HIGH" else 0
        dispute_count += 1 if str(row["dispute_flag"]).lower() == "true" else 0
        ach_returns += 1 if row.get("ach_return_code") else 0
        delinquency_count += 1 if str(row.get("delinquency_bucket", "0")) != "0" else 0
    expected_scale = {
        "target_transaction_rows": target_rows,
        "target_rows_met_by_design": target_rows >= 1_000_000,
        "sample_transaction_rows_written": len(transactions),
        "scale_ratio_sample_to_target": round(len(transactions) / target_rows, 6) if target_rows else 0,
    }
    issues = []
    if orphan_accounts:
        issues.append("orphan_accounts")
    if orphan_transactions:
        issues.append("orphan_transactions")
    if "DELINQUENCY" not in lifecycle_counts and "CHARGEOFF" not in lifecycle_counts:
        issues.append("missing_lending_stress_lifecycle")
    if tca and not tca_metrics:
        issues.append("missing_tca_metrics")
    status = "PASS" if not issues else "WARN"
    return {
        "status": status,
        "issues": issues,
        "synthetic_only": True,
        "referential_integrity": {
            "clients": len(clients),
            "accounts": len(accounts),
            "transactions": len(transactions),
            "orphan_accounts": orphan_accounts,
            "orphan_transactions": orphan_transactions,
        },
        "lifecycle_counts": lifecycle_counts,
        "channel_counts": channel_counts,
        "risk_metrics": {
            "high_risk_transaction_count": high_risk_tx,
            "dispute_count": dispute_count,
            "ach_return_count": ach_returns,
            "delinquency_count": delinquency_count,
        },
        "tca_best_execution": {
            "enabled": bool(tca),
            "metric_rows": len(tca_metrics),
            "best_execution_evidence_rows": len(best_execution),
            "review_count": sum(1 for row in best_execution if row.get("result") == "REVIEW"),
            "pass_count": sum(1 for row in best_execution if row.get("result") == "PASS"),
        },
        "scale": expected_scale,
    }


def advanced_correlations(sample: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    transactions = sample.get("transactions", [])
    if not transactions:
        return []
    total = len(transactions)
    high_risk = [row for row in transactions if row["risk_tier_at_event"] in {"ELEVATED", "HIGH"}]
    low_risk = [row for row in transactions if row["risk_tier_at_event"] in {"LOW", "MEDIUM"}]

    def rate(rows: List[Dict[str, Any]], predicate: str) -> float:
        if not rows:
            return 0.0
        if predicate == "dispute":
            hits = sum(1 for row in rows if str(row["dispute_flag"]).lower() == "true")
        elif predicate == "delinquency":
            hits = sum(1 for row in rows if str(row["delinquency_bucket"]) != "0")
        elif predicate == "ach_return":
            hits = sum(1 for row in rows if row["ach_return_code"])
        else:
            hits = 0
        return round(hits / len(rows), 4)

    large_tx = [row for row in transactions if abs(float(row["amount"])) >= 5000]
    wire_p2p = [row for row in transactions if row["channel"] in {"WIRE", "P2P"}]
    rows = [
        {
            "name": "risk_tier_to_dispute_rate",
            "finding": "Elevated/high risk tiers should show higher dispute pressure.",
            "high_risk_rate": rate(high_risk, "dispute"),
            "low_risk_rate": rate(low_risk, "dispute"),
        },
        {
            "name": "risk_tier_to_delinquency",
            "finding": "Lending delinquency should increase with risk tier.",
            "high_risk_rate": rate(high_risk, "delinquency"),
            "low_risk_rate": rate(low_risk, "delinquency"),
        },
        {
            "name": "ach_return_signal",
            "finding": "ACH return codes should be sparse but measurable.",
            "overall_rate": rate(transactions, "ach_return"),
            "transaction_count": total,
        },
        {
            "name": "large_payment_fraud_pressure",
            "finding": "Large payments and wire/P2P channels carry higher fraud-score pressure.",
            "large_payment_share": round(len(large_tx) / total, 4),
            "wire_p2p_share": round(len(wire_p2p) / total, 4),
        },
    ]
    tca = sample.get("tca", {})
    metrics = tca.get("tca_metrics", []) if isinstance(tca, dict) else []
    if metrics:
        by_strategy: Dict[str, List[float]] = {}
        by_venue: Dict[str, List[float]] = {}
        for row in metrics:
            by_strategy.setdefault(str(row.get("strategy", "")), []).append(float(row.get("arrival_cost_bps", 0)))
            by_venue.setdefault(str(row.get("venue", "")), []).append(float(row.get("slippage_bps", 0)))
        strategy_cost = {key: round(sum(vals) / len(vals), 3) for key, vals in by_strategy.items() if vals}
        venue_cost = {key: round(sum(vals) / len(vals), 3) for key, vals in by_venue.items() if vals}
        rows.extend([
            {
                "name": "strategy_to_arrival_cost",
                "finding": "Execution strategy can be drilled down to arrival cost in bps.",
                "average_arrival_cost_bps_by_strategy": strategy_cost,
            },
            {
                "name": "venue_to_slippage",
                "finding": "Venue-level slippage can be compared without pre-aggregation limits.",
                "average_slippage_bps_by_venue": venue_cost,
            },
        ])
    return rows


def technical_documentation(package: Dict[str, Any]) -> str:
    rules = "\n".join(f"- {row['id']} ({row['domain']}, {row['severity']}): {row['rule']}" for row in domain_rules())
    constraints = "\n".join(f"- {row['area']}: {row['constraint']}" for row in institution_constraints())
    tables = "\n".join([
        "- clients: client_id, segment, synthetic_name, kyc_status, risk_tier, credit_score, annual_income, debt_to_income, onboarded_at, lifecycle_stage, state",
        "- accounts: account_id, client_id, account_type, opened_at, status, credit_limit, interest_rate, institution_program",
        "- transactions: transaction_id, account_id, client_id, posted_at, channel, amount, currency, lifecycle_stage, risk_tier_at_event, fraud_score, dispute_flag, ach_return_code, delinquency_bucket, trace_id",
    ])
    return f"""# {DATASET_NAME}

Version: {DATASET_VERSION}
Package ID: {package['package_id']}
Generated: {package['generated_at']}

## Purpose
This PMO module creates and validates a synthetic, audit-ready multi-table financial dataset for banking, lending, and payments research. It is not connected to PMO trading execution and must not be used as real customer data.

## Scale
- Target transaction rows: {package['target_rows']:,}
- Sample transaction rows written: {package['row_counts']['transactions']:,}
- 1M+ row design: {package['scale_ready']}

## Tables
{tables}

## TCA And Best Execution Repository
The package also models a governed execution-quality repository. It consolidates parent orders, child orders, algo events, RFQs, axes, fills, market data, TCA metrics, and best-execution evidence. It supports real-time-style drill-down by trader, desk, venue, strategy, symbol, portfolio, and time period.

### TCA Tables
{chr(10).join(f"- {row['table']} ({row['grain']}): {row['fields']}" for row in tca_repository_tables())}

### Execution Quality Metrics
{chr(10).join(f"- {row['metric']}: {row['definition']}" for row in tca_metric_definitions())}

### MiFID II / Best Execution Controls
{chr(10).join(f"- {row['control']}: {row['purpose']}" for row in mifid_best_execution_controls())}

### Pre-Trade Intelligence
{chr(10).join(f"- {row['capability']}: {row['description']}" for row in pre_trade_intelligence_capabilities())}

### Governed Historical Market Data And Backtesting
{chr(10).join(f"- {row['capability']}: {row['description']}" for row in governed_market_data_capabilities())}

## Behavioral Logic
- Client risk tier drives fraud pressure, delinquency probability, ACH returns, and dispute frequency.
- Account type affects channel mix, credit exposure, interest rate, settlement behavior, and lifecycle states.
- Transaction lifecycle covers onboarding, activity, loan application, disbursement, repayment, delinquency, cure, chargeoff, dispute, and closure.
- Payment channels include ACH, card, wire, ATM, bill pay, P2P, merchant, and loan events.

## Advanced Correlations
Correlations are computed into the validation report and include risk-tier/dispute, risk-tier/delinquency, ACH-return signal, and large-payment fraud pressure.

## Domain Rules
{rules}

## Institution-Specific Constraints
{constraints}

## Audit Controls
- Synthetic-only attestation is included in every report.
- Files include package id, generated timestamp, row counts, validation status, and documentation path.
- Full 1M+ generation requires explicit confirmation text to avoid accidental large file writes.

## NDA And Support Process
NDA and support process documents are generated beside this technical package. They are templates only and require owner/legal review before external use.
"""


def nda_process_doc(package: Dict[str, Any]) -> str:
    return f"""# PMO Financial Dataset NDA Process

Package ID: {package['package_id']}
Status: Template only - owner/legal review required.

## Intended Workflow
1. Confirm the recipient and institution purpose.
2. Share only synthetic dataset documentation until NDA is signed.
3. Verify that no real customer data, routing numbers, account numbers, SSNs, card numbers, or credentials are included.
4. Require written acceptance of synthetic-only use, no re-identification attempts, no credential storage, and no production banking decisioning.
5. Record NDA status in PMO before releasing generated dataset files.

## Required NDA Fields
- Recipient legal name
- Institution or company
- Authorized contact email
- Dataset package id
- Permitted research purpose
- Retention period
- Redistribution restriction
- Security contact

## PMO Rule
PMO can track NDA status, but PMO does not create legal approval. Final approval must come from the owner or legal counsel.
"""


def support_channel_doc(package: Dict[str, Any]) -> str:
    return f"""# PMO Financial Dataset Dedicated Support Channel

Package ID: {package['package_id']}
Status: Template only - configure actual channel before external distribution.

## Channel Options
- Dedicated email alias
- Private Discord channel
- Private Slack channel
- Ticket queue

## Intake Fields
- Dataset package id
- Requester name and institution
- Issue category: data dictionary, validation, domain rule, generation error, access request, NDA status
- Severity: low, medium, high, urgent
- Expected response window

## Support Rules
- Do not accept real customer data in support messages.
- Do not request bank credentials, card numbers, SSNs, seed phrases, passwords, or API secrets.
- Keep audit logs for dataset releases and support decisions.
"""


def build_financial_dataset_status(settings: Dict[str, Any], pmo_dir: Path, csv_dir: Path, report_dir: Path) -> Dict[str, Any]:
    cfg = finance_dataset_settings(settings)
    table_names = ["clients", "accounts", "transactions", *[row["table"] for row in tca_repository_tables()]]
    validation_file = report_dir / "pmo_financial_dataset_validation_summary.json"
    audit_file = report_dir / "pmo_financial_dataset_audit_package.json"
    latest_validation = {}
    latest_audit = {}
    if validation_file.exists():
        try:
            latest_validation = json.loads(validation_file.read_text(encoding="utf-8"))
        except Exception:
            latest_validation = {"status": "UNREADABLE"}
    if audit_file.exists():
        try:
            latest_audit = json.loads(audit_file.read_text(encoding="utf-8"))
        except Exception:
            latest_audit = {"status": "UNREADABLE"}
    return {
        "ok": True,
        "enabled": cfg["enabled"],
        "dataset_name": DATASET_NAME,
        "version": DATASET_VERSION,
        "synthetic_only": cfg["synthetic_only"],
        "target_rows": cfg["target_rows"],
        "large_scale_ready": cfg["target_rows"] >= 1_000_000,
        "tables": table_names,
        "lifecycle_stages": list(LIFECYCLE_STAGES),
        "tca_repository_tables": tca_repository_tables(),
        "tca_metric_definitions": tca_metric_definitions(),
        "mifid_best_execution_controls": mifid_best_execution_controls(),
        "pre_trade_intelligence": pre_trade_intelligence_capabilities(),
        "governed_market_data": governed_market_data_capabilities(),
        "domain_rules": domain_rules(),
        "institution_constraints": institution_constraints(),
        "latest_validation": latest_validation,
        "latest_audit": latest_audit,
        "files": {
            "dataset_root": str(pmo_dir / "pmo_financial_datasets"),
            "validation_summary": str(validation_file),
            "audit_package": str(audit_file),
            "technical_documentation": str(report_dir / "pmo_financial_dataset_technical_documentation.md"),
            "nda_process": str(report_dir / "pmo_financial_dataset_nda_process.md"),
            "support_channel": str(report_dir / "pmo_financial_dataset_support_channel.md"),
            "manifest": str(csv_dir / "pmo_financial_dataset_manifest.csv"),
        },
        "safety": {
            "live_trading_changed": False,
            "orders_placed": False,
            "real_customer_data_allowed": False,
        },
    }


def prepare_financial_dataset_package(
    settings: Dict[str, Any],
    pmo_dir: Path,
    csv_dir: Path,
    report_dir: Path,
    rows: Optional[int] = None,
    mode: str = "sample",
    confirm_text: str = "",
) -> Dict[str, Any]:
    cfg = finance_dataset_settings(settings)
    if not cfg["enabled"]:
        return {"ok": False, "error": "ENABLE_PMO_FINANCIAL_DATASET_LAB=False", "orders_placed": False, "live_trading_changed": False}
    requested_rows = max(100, _safe_int(rows, cfg["default_sample_rows"]))
    full_mode = str(mode).lower() in {"full", "large", "1m", "production_scale"}
    if full_mode:
        requested_rows = max(1_000_000, requested_rows)
    requested_rows = min(requested_rows, cfg["max_generate_rows"])
    if requested_rows > 50_000 and confirm_text != "GENERATE FINANCIAL DATASET":
        return {
            "ok": False,
            "error": "Large dataset generation requires confirm_text='GENERATE FINANCIAL DATASET'.",
            "requested_rows": requested_rows,
            "orders_placed": False,
            "live_trading_changed": False,
        }

    sample_rows = requested_rows if requested_rows <= 50_000 else 10_000
    client_count = max(25, min(50_000, math.ceil(sample_rows / 25)))
    account_count = max(client_count, math.ceil(client_count * 1.6))
    package_id = f"PMO-FIN-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    dataset_dir = pmo_dir / "pmo_financial_datasets" / package_id
    sample = _iter_sample(client_count, account_count, sample_rows)
    tca_order_count = max(25, min(2500, math.ceil(sample_rows / 40)))
    tca = _tca_sample(tca_order_count, random.Random(1206), datetime.now() - timedelta(days=365))
    sample["tca"] = tca

    row_counts = {
        "clients": _write_table(dataset_dir / "clients.csv", sample["clients"]),
        "accounts": _write_table(dataset_dir / "accounts.csv", sample["accounts"]),
        "transactions": _write_table(dataset_dir / "transactions.csv", sample["transactions"]),
    }
    for table_name, table_rows in tca.items():
        row_counts[table_name] = _write_table(dataset_dir / f"{table_name}.csv", table_rows)
    validation = validation_summary(sample, requested_rows)
    correlations = advanced_correlations(sample)
    package = {
        "ok": True,
        "package_id": package_id,
        "generated_at": _now_iso(),
        "dataset_name": DATASET_NAME,
        "version": DATASET_VERSION,
        "mode": "FULL_SCALE_MANIFEST_WITH_SAMPLE" if requested_rows > sample_rows else "SAMPLE_DATASET",
        "target_rows": requested_rows,
        "scale_ready": requested_rows >= 1_000_000,
        "synthetic_only": True,
        "dataset_dir": str(dataset_dir),
        "row_counts": row_counts,
        "tables": ["clients", "accounts", "transactions", *list(tca.keys())],
        "lifecycle_stages": list(LIFECYCLE_STAGES),
        "tca_repository_tables": tca_repository_tables(),
        "tca_metric_definitions": tca_metric_definitions(),
        "mifid_best_execution_controls": mifid_best_execution_controls(),
        "pre_trade_intelligence": pre_trade_intelligence_capabilities(),
        "governed_market_data": governed_market_data_capabilities(),
        "domain_rules": domain_rules(),
        "institution_constraints": institution_constraints(),
        "advanced_correlations": correlations,
        "validation": validation,
        "safety": {
            "real_customer_data_allowed": False,
            "live_trading_changed": False,
            "orders_placed": False,
            "broker_api_called": False,
        },
    }

    validation_file = report_dir / "pmo_financial_dataset_validation_summary.json"
    audit_file = report_dir / "pmo_financial_dataset_audit_package.json"
    doc_file = report_dir / "pmo_financial_dataset_technical_documentation.md"
    nda_file = report_dir / "pmo_financial_dataset_nda_process.md"
    support_file = report_dir / "pmo_financial_dataset_support_channel.md"
    manifest_file = csv_dir / "pmo_financial_dataset_manifest.csv"

    package["files"] = {
        "validation_summary": str(validation_file),
        "audit_package": str(audit_file),
        "technical_documentation": str(doc_file),
        "nda_process": str(nda_file),
        "support_channel": str(support_file),
        "manifest": str(manifest_file),
        "clients_csv": str(dataset_dir / "clients.csv"),
        "accounts_csv": str(dataset_dir / "accounts.csv"),
        "transactions_csv": str(dataset_dir / "transactions.csv"),
        "parent_orders_csv": str(dataset_dir / "parent_orders.csv"),
        "child_orders_csv": str(dataset_dir / "child_orders.csv"),
        "fills_csv": str(dataset_dir / "fills.csv"),
        "tca_metrics_csv": str(dataset_dir / "tca_metrics.csv"),
        "best_execution_evidence_csv": str(dataset_dir / "best_execution_evidence.csv"),
    }
    _write_json(validation_file, validation)
    _write_json(audit_file, package)
    _write_text(doc_file, technical_documentation(package))
    _write_text(nda_file, nda_process_doc(package))
    _write_text(support_file, support_channel_doc(package))
    _append_manifest(manifest_file, {
        "timestamp": package["generated_at"],
        "package_id": package_id,
        "mode": package["mode"],
        "target_rows": requested_rows,
        "client_rows": row_counts["clients"],
        "account_rows": row_counts["accounts"],
        "transaction_rows": row_counts["transactions"],
        "dataset_dir": str(dataset_dir),
        "validation_status": validation["status"],
        "documentation_file": str(doc_file),
        "audit_package_file": str(audit_file),
    })
    return package


def _read_csv_rows(path: Path, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    if not path.exists() or path.stat().st_size <= 0:
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(dict(row))
            if limit and len(rows) >= limit:
                break
    return rows


def _latest_package(report_dir: Path) -> Dict[str, Any]:
    audit_file = report_dir / "pmo_financial_dataset_audit_package.json"
    if not audit_file.exists():
        return {}
    try:
        return json.loads(audit_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _latest_dataset_dir(report_dir: Path) -> Optional[Path]:
    package = _latest_package(report_dir)
    dataset_dir = package.get("dataset_dir")
    if not dataset_dir:
        return None
    path = Path(str(dataset_dir))
    return path if path.exists() else None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _matches_filters(row: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    for key, value in (filters or {}).items():
        if value in (None, "", [], {}):
            continue
        if key not in row:
            continue
        values = value if isinstance(value, list) else [value]
        normalized = {str(item).strip().upper() for item in values}
        if str(row.get(key, "")).strip().upper() not in normalized:
            return False
    return True


def _metric_summary(rows: List[Dict[str, Any]], metrics: List[str]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"count": len(rows)}
    for metric in metrics:
        vals = [_safe_float(row.get(metric), 0.0) for row in rows if str(row.get(metric, "")).strip() != ""]
        if not vals:
            summary[f"avg_{metric}"] = 0
            summary[f"min_{metric}"] = 0
            summary[f"max_{metric}"] = 0
            continue
        summary[f"avg_{metric}"] = round(sum(vals) / len(vals), 4)
        summary[f"min_{metric}"] = round(min(vals), 4)
        summary[f"max_{metric}"] = round(max(vals), 4)
    return summary


def tca_self_service_status(report_dir: Path) -> Dict[str, Any]:
    dataset_dir = _latest_dataset_dir(report_dir)
    package = _latest_package(report_dir)
    return {
        "ok": True,
        "enabled": True,
        "latest_package_id": package.get("package_id", ""),
        "dataset_dir": str(dataset_dir) if dataset_dir else "",
        "available_dimensions": list(TCA_DIMENSIONS),
        "available_metrics": list(TCA_METRICS),
        "custom_metric_modes": ["average", "min", "max", "spread", "weighted_composite"],
        "natural_language_querying": True,
        "ai_driven_outlier_detection": "LOCAL_RULE_BASED",
        "self_service_dashboards": True,
        "safety": {
            "orders_placed": False,
            "live_trading_changed": False,
            "real_customer_data_allowed": False,
        },
    }


def run_tca_self_service_query(
    report_dir: Path,
    dimensions: Optional[List[str]] = None,
    metrics: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    dataset_dir = _latest_dataset_dir(report_dir)
    if not dataset_dir:
        return {"ok": False, "error": "No generated financial dataset package found.", "orders_placed": False, "live_trading_changed": False}
    dimensions = [dim for dim in (dimensions or ["strategy"]) if dim in TCA_DIMENSIONS]
    metrics = [metric for metric in (metrics or ["slippage_bps", "arrival_cost_bps", "opportunity_cost_bps"]) if metric in TCA_METRICS]
    if not dimensions:
        dimensions = ["strategy"]
    if not metrics:
        metrics = ["slippage_bps"]
    rows = _read_csv_rows(dataset_dir / "tca_metrics.csv")
    rows = [row for row in rows if _matches_filters(row, filters or {})]
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        key = " | ".join(str(row.get(dim, "")) for dim in dimensions)
        groups.setdefault(key, []).append(row)
    result_rows = []
    for key, group_rows in groups.items():
        parts = key.split(" | ")
        item = {dim: parts[idx] if idx < len(parts) else "" for idx, dim in enumerate(dimensions)}
        item.update(_metric_summary(group_rows, metrics))
        result_rows.append(item)
    primary_metric = f"avg_{metrics[0]}"
    result_rows.sort(key=lambda row: abs(_safe_float(row.get(primary_metric), 0.0)), reverse=True)
    return {
        "ok": True,
        "mode": "SELF_SERVICE_TCA_QUERY",
        "dimensions": dimensions,
        "metrics": metrics,
        "filters": filters or {},
        "row_count": len(rows),
        "group_count": len(result_rows),
        "rows": result_rows[: max(1, min(500, int(limit)))],
        "drilldown_available": True,
        "dataset_dir": str(dataset_dir),
        "orders_placed": False,
        "live_trading_changed": False,
    }


def detect_tca_outliers(report_dir: Path, metric: str = "arrival_cost_bps", z_threshold: float = 2.0, limit: int = 25) -> Dict[str, Any]:
    dataset_dir = _latest_dataset_dir(report_dir)
    if not dataset_dir:
        return {"ok": False, "error": "No generated financial dataset package found.", "orders_placed": False, "live_trading_changed": False}
    metric = metric if metric in TCA_METRICS else "arrival_cost_bps"
    rows = _read_csv_rows(dataset_dir / "tca_metrics.csv")
    vals = [_safe_float(row.get(metric), 0.0) for row in rows]
    if not vals:
        return {"ok": True, "metric": metric, "outliers": [], "summary": {"count": 0}, "orders_placed": False, "live_trading_changed": False}
    mean = sum(vals) / len(vals)
    variance = sum((value - mean) ** 2 for value in vals) / max(1, len(vals) - 1)
    std = math.sqrt(variance) if variance > 0 else 0.0
    outliers = []
    for row in rows:
        value = _safe_float(row.get(metric), 0.0)
        z_score = 0.0 if std == 0 else (value - mean) / std
        if abs(z_score) >= z_threshold:
            outliers.append({
                "entity_id": row.get("entity_id", ""),
                "trader_id": row.get("trader_id", ""),
                "desk_id": row.get("desk_id", ""),
                "venue": row.get("venue", ""),
                "strategy": row.get("strategy", ""),
                "period": row.get("period", ""),
                "metric": metric,
                "value": round(value, 4),
                "z_score": round(z_score, 3),
                "reason": f"{metric} z-score {z_score:.2f} exceeds threshold {z_threshold:g}",
            })
    outliers.sort(key=lambda row: abs(_safe_float(row.get("z_score"), 0.0)), reverse=True)
    return {
        "ok": True,
        "mode": "AI_DRIVEN_EXECUTION_ANOMALY_DETECTION",
        "engine": "LOCAL_RULE_BASED_ZSCORE",
        "metric": metric,
        "threshold": z_threshold,
        "summary": {"count": len(rows), "mean": round(mean, 4), "std": round(std, 4), "outlier_count": len(outliers)},
        "outliers": outliers[: max(1, min(500, int(limit)))],
        "orders_placed": False,
        "live_trading_changed": False,
    }


def run_custom_tca_metric(report_dir: Path, spec: Dict[str, Any]) -> Dict[str, Any]:
    metric_name = str(spec.get("name") or "custom_metric").strip()[:80]
    mode = str(spec.get("mode") or "weighted_composite").strip().lower()
    weights = spec.get("weights") if isinstance(spec.get("weights"), dict) else {}
    dimensions = spec.get("dimensions") if isinstance(spec.get("dimensions"), list) else ["strategy"]
    query = run_tca_self_service_query(report_dir, dimensions=dimensions, metrics=list(TCA_METRICS), filters=spec.get("filters") or {}, limit=500)
    if not query.get("ok"):
        return query
    rows = []
    for row in query.get("rows", []):
        if mode == "spread":
            metric = _safe_float(row.get("max_slippage_bps"), 0) - _safe_float(row.get("min_slippage_bps"), 0)
        elif mode == "average":
            metric = _safe_float(row.get("avg_arrival_cost_bps"), 0)
        else:
            metric = 0.0
            for key, weight in weights.items():
                if key in TCA_METRICS:
                    metric += _safe_float(row.get(f"avg_{key}"), 0.0) * _safe_float(weight, 0.0)
        enriched = dict(row)
        enriched[metric_name] = round(metric, 4)
        rows.append(enriched)
    rows.sort(key=lambda row: abs(_safe_float(row.get(metric_name), 0.0)), reverse=True)
    return {
        "ok": True,
        "mode": "CUSTOM_TCA_METRIC",
        "metric_name": metric_name,
        "metric_mode": mode,
        "weights": weights,
        "dimensions": dimensions,
        "rows": rows[: max(1, min(500, _safe_int(spec.get("limit"), 50)))],
        "orders_placed": False,
        "live_trading_changed": False,
    }


def natural_language_tca_query(report_dir: Path, question: str) -> Dict[str, Any]:
    text = str(question or "").strip()
    lowered = text.lower()
    dimensions = []
    for dim in TCA_DIMENSIONS:
        if dim.replace("_id", "").replace("_", " ") in lowered or dim in lowered:
            dimensions.append(dim)
    if "trader" in lowered and "trader_id" not in dimensions:
        dimensions.append("trader_id")
    if "desk" in lowered and "desk_id" not in dimensions:
        dimensions.append("desk_id")
    if "venue" in lowered and "venue" not in dimensions:
        dimensions.append("venue")
    if "strategy" in lowered and "strategy" not in dimensions:
        dimensions.append("strategy")
    if "time" in lowered or "period" in lowered or "day" in lowered:
        if "period" not in dimensions:
            dimensions.append("period")
    if not dimensions:
        dimensions = ["strategy"]

    metrics = []
    metric_aliases = {
        "slippage": "slippage_bps",
        "impact": "market_impact_bps",
        "market impact": "market_impact_bps",
        "timing": "timing_cost_bps",
        "opportunity": "opportunity_cost_bps",
        "arrival": "arrival_cost_bps",
        "shortfall": "arrival_cost_bps",
        "fill rate": "fill_rate",
    }
    for alias, metric in metric_aliases.items():
        if alias in lowered and metric not in metrics:
            metrics.append(metric)
    if not metrics:
        metrics = ["slippage_bps", "arrival_cost_bps", "opportunity_cost_bps"]

    filters: Dict[str, Any] = {}
    for strategy in EXECUTION_STRATEGIES:
        if strategy.lower() in lowered:
            filters["strategy"] = strategy
    for venue in TRADING_VENUES:
        if venue.lower() in lowered:
            filters["venue"] = venue
    symbol_match = re.search(r"\b([A-Z]{1,5})\b", text)
    if symbol_match and symbol_match.group(1) not in {"TCA", "PMO", "RFQ", "OMS", "EMS"}:
        # tca_metrics itself does not carry symbol in this synthetic sample, so keep the parsed value in the response.
        filters["_parsed_symbol_note"] = symbol_match.group(1)

    wants_outliers = any(word in lowered for word in ("outlier", "anomaly", "worst", "bad", "issue", "problem"))
    if wants_outliers:
        outlier_metric = metrics[0]
        result = detect_tca_outliers(report_dir, metric=outlier_metric, limit=25)
        result["interpreted_question"] = {"dimensions": dimensions, "metrics": metrics, "filters": filters, "intent": "outlier_detection"}
        return result
    result = run_tca_self_service_query(report_dir, dimensions=dimensions, metrics=metrics, filters={k: v for k, v in filters.items() if not k.startswith("_")}, limit=25)
    result["interpreted_question"] = {"dimensions": dimensions, "metrics": metrics, "filters": filters, "intent": "comparative_analysis"}
    return result


def generate_tca_self_service_report(report_dir: Path, title: str = "PMO TCA Self-Service Report") -> Dict[str, Any]:
    dataset_dir = _latest_dataset_dir(report_dir)
    if not dataset_dir:
        return {"ok": False, "error": "No generated financial dataset package found.", "orders_placed": False, "live_trading_changed": False}
    by_strategy = run_tca_self_service_query(report_dir, dimensions=["strategy"], metrics=["slippage_bps", "arrival_cost_bps", "opportunity_cost_bps"], limit=20)
    by_venue = run_tca_self_service_query(report_dir, dimensions=["venue"], metrics=["slippage_bps", "market_impact_bps"], limit=20)
    outliers = detect_tca_outliers(report_dir, metric="arrival_cost_bps", limit=10)
    package = _latest_package(report_dir)
    report_path = report_dir / "pmo_tca_self_service_report.md"
    lines = [
        f"# {title}",
        "",
        f"Generated: {_now_iso()}",
        f"Package: {package.get('package_id', '')}",
        "",
        "## Scope",
        "Self-service execution analytics across trader, desk, venue, strategy, and time period. Synthetic PMO dataset only.",
        "",
        "## Strategy Comparison",
    ]
    for row in by_strategy.get("rows", [])[:10]:
        lines.append(f"- {row.get('strategy')}: avg slippage {row.get('avg_slippage_bps')} bps, avg arrival cost {row.get('avg_arrival_cost_bps')} bps, avg opportunity cost {row.get('avg_opportunity_cost_bps')} bps")
    lines.extend(["", "## Venue Comparison"])
    for row in by_venue.get("rows", [])[:10]:
        lines.append(f"- {row.get('venue')}: avg slippage {row.get('avg_slippage_bps')} bps, avg market impact {row.get('avg_market_impact_bps')} bps")
    lines.extend(["", "## Execution Anomalies"])
    for row in outliers.get("outliers", [])[:10]:
        lines.append(f"- {row.get('entity_id')} {row.get('strategy')} {row.get('venue')}: {row.get('metric')}={row.get('value')} bps, z={row.get('z_score')}")
    lines.extend([
        "",
        "## Compliance Note",
        "This report preserves granular parent-order, child-order, fill, market-data, and best-execution evidence lineage. It is synthetic and does not alter PMO trading settings.",
    ])
    _write_text(report_path, "\n".join(lines) + "\n")
    return {
        "ok": True,
        "report_file": str(report_path),
        "by_strategy": by_strategy,
        "by_venue": by_venue,
        "outliers": outliers,
        "orders_placed": False,
        "live_trading_changed": False,
    }


def pre_trade_cost_model(report_dir: Path, scenario: Dict[str, Any]) -> Dict[str, Any]:
    dataset_dir = _latest_dataset_dir(report_dir)
    if not dataset_dir:
        return {"ok": False, "error": "No generated financial dataset package found.", "orders_placed": False, "live_trading_changed": False}
    symbol = str(scenario.get("symbol") or "SPY").upper()[:12]
    side = str(scenario.get("side") or "BUY").upper()
    qty = max(1, _safe_int(scenario.get("quantity"), 1000))
    strategy = str(scenario.get("strategy") or "VWAP").upper()
    urgency = str(scenario.get("urgency") or "NORMAL").upper()
    venue = str(scenario.get("venue") or "").upper()
    metrics = _read_csv_rows(dataset_dir / "tca_metrics.csv")
    candidates = [row for row in metrics if (not strategy or row.get("strategy") == strategy)]
    if venue:
        venue_rows = [row for row in candidates if row.get("venue") == venue]
        if venue_rows:
            candidates = venue_rows
    if not candidates:
        candidates = metrics
    base = _metric_summary(candidates, ["slippage_bps", "market_impact_bps", "timing_cost_bps", "opportunity_cost_bps", "arrival_cost_bps", "fill_rate"])
    size_factor = min(4.0, max(0.25, math.sqrt(qty / 1000)))
    urgency_factor = {"LOW": 0.75, "NORMAL": 1.0, "HIGH": 1.35, "URGENT": 1.8}.get(urgency, 1.0)
    expected = {
        "expected_slippage_bps": round(_safe_float(base.get("avg_slippage_bps"), 0) * size_factor * urgency_factor, 3),
        "expected_market_impact_bps": round(abs(_safe_float(base.get("avg_market_impact_bps"), 0)) * size_factor * urgency_factor, 3),
        "expected_timing_cost_bps": round(abs(_safe_float(base.get("avg_timing_cost_bps"), 0)) * urgency_factor, 3),
        "expected_opportunity_cost_bps": round(abs(_safe_float(base.get("avg_opportunity_cost_bps"), 0)) / max(0.5, urgency_factor), 3),
        "expected_arrival_cost_bps": round(_safe_float(base.get("avg_arrival_cost_bps"), 0) * size_factor * urgency_factor, 3),
        "expected_fill_rate": round(min(1.0, max(0.0, _safe_float(base.get("avg_fill_rate"), 0.85) / max(1.0, size_factor / 2))), 4),
    }
    venue_scores: List[Dict[str, Any]] = []
    for row in run_tca_self_service_query(report_dir, dimensions=["venue"], metrics=["slippage_bps", "market_impact_bps", "opportunity_cost_bps", "fill_rate"], limit=50).get("rows", []):
        cost = abs(_safe_float(row.get("avg_slippage_bps"), 0)) + abs(_safe_float(row.get("avg_market_impact_bps"), 0)) + abs(_safe_float(row.get("avg_opportunity_cost_bps"), 0))
        fill_bonus = _safe_float(row.get("avg_fill_rate"), 0) * 20
        venue_scores.append({"venue": row.get("venue", ""), "score": round(fill_bonus - cost, 3), "expected_cost_bps": round(cost, 3), "fill_rate": row.get("avg_fill_rate", 0)})
    venue_scores.sort(key=lambda row: row["score"], reverse=True)
    strategy_rows = run_tca_self_service_query(report_dir, dimensions=["strategy"], metrics=["arrival_cost_bps", "opportunity_cost_bps", "fill_rate"], limit=50).get("rows", [])
    strategy_scores = []
    for row in strategy_rows:
        cost = abs(_safe_float(row.get("avg_arrival_cost_bps"), 0)) + abs(_safe_float(row.get("avg_opportunity_cost_bps"), 0))
        strategy_scores.append({"strategy": row.get("strategy", ""), "expected_cost_bps": round(cost, 3), "fill_rate": row.get("avg_fill_rate", 0)})
    strategy_scores.sort(key=lambda row: row["expected_cost_bps"])
    return {
        "ok": True,
        "mode": "PRE_TRADE_INTELLIGENCE",
        "scenario": {"symbol": symbol, "side": side, "quantity": qty, "strategy": strategy, "urgency": urgency, "venue": venue or "AUTO"},
        "expected_costs": expected,
        "recommended_venues": venue_scores[:5],
        "recommended_strategies": strategy_scores[:5],
        "what_if_supported": ["quantity", "timing", "venue", "strategy", "urgency"],
        "orders_placed": False,
        "live_trading_changed": False,
    }


def run_execution_what_if(report_dir: Path, scenario: Dict[str, Any]) -> Dict[str, Any]:
    base_qty = max(100, _safe_int(scenario.get("quantity"), 1000))
    strategy = str(scenario.get("strategy") or "VWAP").upper()
    scenarios = []
    for qty_mult in (0.5, 1.0, 2.0):
        for urgency in ("LOW", "NORMAL", "HIGH"):
            item = dict(scenario)
            item["quantity"] = int(base_qty * qty_mult)
            item["urgency"] = urgency
            item["strategy"] = strategy
            result = pre_trade_cost_model(report_dir, item)
            if result.get("ok"):
                scenarios.append({
                    "quantity": item["quantity"],
                    "urgency": urgency,
                    "strategy": strategy,
                    **result.get("expected_costs", {}),
                    "top_venue": (result.get("recommended_venues") or [{}])[0].get("venue", ""),
                })
    scenarios.sort(key=lambda row: abs(_safe_float(row.get("expected_arrival_cost_bps"), 0)) + abs(_safe_float(row.get("expected_opportunity_cost_bps"), 0)))
    return {
        "ok": True,
        "mode": "WHAT_IF_EXECUTION_SCENARIOS",
        "base_scenario": scenario,
        "scenarios": scenarios,
        "best_scenario": scenarios[0] if scenarios else {},
        "orders_placed": False,
        "live_trading_changed": False,
    }


def governed_market_replay(report_dir: Path, horizon: str = "INTRADAY_BAR", stress_period: str = "NORMAL_SESSION") -> Dict[str, Any]:
    horizon = str(horizon or "INTRADAY_BAR").upper()
    stress_period = str(stress_period or "NORMAL_SESSION").upper()
    if horizon not in BACKTEST_HORIZONS:
        horizon = "INTRADAY_BAR"
    if stress_period not in MARKET_STRESS_PERIODS:
        stress_period = "NORMAL_SESSION"
    replay_id = f"PMO-REPLAY-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    volatility_mult = {
        "COVID_LIQUIDITY_SHOCK": 2.8,
        "RATE_HIKE_VOLATILITY": 1.7,
        "BANKING_STRESS": 2.2,
        "MEME_STOCK_VOLATILITY": 3.4,
        "NORMAL_SESSION": 1.0,
    }[stress_period]
    bar_count = {"EOD": 252, "INTRADAY_BAR": 390, "TICK": 5000}[horizon]
    snapshot_label = f"official_close_snapshot_{datetime.now().date().isoformat()}"
    result = {
        "ok": True,
        "mode": "GOVERNED_MARKET_REPLAY",
        "replay_id": replay_id,
        "horizon": horizon,
        "stress_period": stress_period,
        "versioned_snapshot": snapshot_label,
        "bar_or_tick_count": bar_count,
        "assumptions": {
            "volatility_multiplier": volatility_mult,
            "spread_multiplier": round(1.0 + (volatility_mult - 1.0) * 0.45, 3),
            "liquidity_multiplier": round(max(0.2, 1.0 / volatility_mult), 3),
        },
        "reproducibility": {
            "snapshot_locked": True,
            "pre_aggregation_required": False,
            "multi_horizon_supported": list(BACKTEST_HORIZONS),
        },
        "orders_placed": False,
        "live_trading_changed": False,
    }
    _write_json(report_dir / "pmo_governed_market_replay_latest.json", result)
    return result


def market_data_governance_status(report_dir: Path) -> Dict[str, Any]:
    dataset_dir = _latest_dataset_dir(report_dir)
    package = _latest_package(report_dir)
    latest_quality_file = report_dir / "pmo_market_data_quality_latest.json"
    latest_quality = {}
    if latest_quality_file.exists():
        try:
            latest_quality = json.loads(latest_quality_file.read_text(encoding="utf-8"))
        except Exception:
            latest_quality = {"status": "UNREADABLE"}
    return {
        "ok": True,
        "mode": "MARKET_DATA_GOVERNANCE",
        "latest_package_id": package.get("package_id", ""),
        "dataset_dir": str(dataset_dir) if dataset_dir else "",
        "data_model": market_data_model(),
        "quality_rules": market_data_quality_rules(),
        "capabilities": governed_market_data_capabilities(),
        "latest_quality": latest_quality,
        "safety": {"orders_placed": False, "live_trading_changed": False, "real_customer_data_allowed": False},
    }


def run_market_data_quality_checks(report_dir: Path, tolerance_bps: float = 5.0) -> Dict[str, Any]:
    dataset_dir = _latest_dataset_dir(report_dir)
    if not dataset_dir:
        return {"ok": False, "error": "No generated financial dataset package found.", "orders_placed": False, "live_trading_changed": False}
    rows = _read_csv_rows(dataset_dir / "market_data.csv")
    events: List[Dict[str, Any]] = []
    seen = set()
    spreads = []
    vols = []
    for idx, row in enumerate(rows, start=1):
        symbol = str(row.get("symbol", "")).strip().upper()
        timestamp = str(row.get("timestamp", "")).strip()
        bid = _safe_float(row.get("bid"), 0)
        ask = _safe_float(row.get("ask"), 0)
        mid = _safe_float(row.get("mid"), 0)
        last = _safe_float(row.get("last"), 0)
        volume = _safe_float(row.get("volume"), -1)
        vol = _safe_float(row.get("volatility"), 0)
        key = (symbol, timestamp)
        if not symbol or not timestamp or bid <= 0 or ask <= 0 or mid <= 0 or last <= 0:
            events.append({"event_id": f"DQ{idx:06d}", "rule_id": "MD_REQUIRED_FIELDS", "severity": "critical", "symbol": symbol, "timestamp": timestamp, "explanation": "Required market data fields are missing or non-positive."})
        if bid > ask:
            events.append({"event_id": f"DQ{idx:06d}", "rule_id": "MD_BID_ASK_SANITY", "severity": "critical", "symbol": symbol, "timestamp": timestamp, "explanation": f"bid {bid} is greater than ask {ask}."})
        expected_mid = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
        if expected_mid > 0:
            diff_bps = abs((mid - expected_mid) / expected_mid) * 10000
            if diff_bps > tolerance_bps:
                events.append({"event_id": f"DQ{idx:06d}", "rule_id": "MD_MID_CONSISTENCY", "severity": "high", "symbol": symbol, "timestamp": timestamp, "field": "mid", "observed": mid, "expected": round(expected_mid, 6), "explanation": f"mid differs from bid/ask midpoint by {diff_bps:.2f} bps."})
        if key in seen:
            events.append({"event_id": f"DQ{idx:06d}", "rule_id": "MD_DUPLICATE_SNAPSHOT", "severity": "medium", "symbol": symbol, "timestamp": timestamp, "explanation": "Duplicate symbol/timestamp snapshot."})
        seen.add(key)
        if volume < 0:
            events.append({"event_id": f"DQ{idx:06d}", "rule_id": "MD_VOLUME_COMPLETENESS", "severity": "medium", "symbol": symbol, "timestamp": timestamp, "field": "volume", "observed": volume, "expected": ">= 0", "explanation": "Volume is missing or negative."})
        if expected_mid > 0:
            spreads.append(((ask - bid) / expected_mid) * 10000)
        vols.append(vol)

    def outlier_events(values: List[float], rule_id: str, field: str) -> None:
        if len(values) < 5:
            return
        mean = sum(values) / len(values)
        std = math.sqrt(sum((value - mean) ** 2 for value in values) / max(1, len(values) - 1))
        if std <= 0:
            return
        for row_idx, value in enumerate(values, start=1):
            z = (value - mean) / std
            if abs(z) >= 3:
                row = rows[row_idx - 1]
                events.append({"event_id": f"DQO{row_idx:06d}", "rule_id": rule_id, "severity": "medium", "symbol": row.get("symbol", ""), "timestamp": row.get("timestamp", ""), "field": field, "observed": round(value, 4), "expected": f"z-score < 3; observed {z:.2f}", "explanation": f"{field} is an outlier versus the sample distribution."})

    outlier_events(spreads, "MD_OUTLIER_SPREAD", "spread_bps")
    outlier_events(vols, "MD_OUTLIER_SPREAD", "volatility")
    status = "PASS" if not any(event.get("severity") in {"critical", "high"} for event in events) else "REVIEW"
    report = {
        "ok": True,
        "status": status,
        "row_count": len(rows),
        "event_count": len(events),
        "critical_count": sum(1 for event in events if event.get("severity") == "critical"),
        "high_count": sum(1 for event in events if event.get("severity") == "high"),
        "medium_count": sum(1 for event in events if event.get("severity") == "medium"),
        "events": events[:250],
        "metadata": {
            "dataset_dir": str(dataset_dir),
            "quality_rules": market_data_quality_rules(),
            "tolerance_bps": tolerance_bps,
            "snapshot_version": f"quality_snapshot_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        },
        "orders_placed": False,
        "live_trading_changed": False,
    }
    _write_json(report_dir / "pmo_market_data_quality_latest.json", report)
    return report


def run_market_data_query(report_dir: Path, spec: Dict[str, Any]) -> Dict[str, Any]:
    dataset_dir = _latest_dataset_dir(report_dir)
    if not dataset_dir:
        return {"ok": False, "error": "No generated financial dataset package found.", "orders_placed": False, "live_trading_changed": False}
    rows = _read_csv_rows(dataset_dir / "market_data.csv")
    symbol_filter = str(spec.get("symbol") or "").upper().strip()
    if symbol_filter:
        rows = [row for row in rows if str(row.get("symbol", "")).upper() == symbol_filter]
    groups: Dict[str, List[Dict[str, Any]]] = {}
    group_by = str(spec.get("group_by") or "symbol")
    if group_by not in {"symbol", "date"}:
        group_by = "symbol"
    for row in rows:
        if group_by == "date":
            key = str(row.get("timestamp", ""))[:10]
        else:
            key = str(row.get("symbol", ""))
        groups.setdefault(key, []).append(row)
    out_rows = []
    for key, group_rows in groups.items():
        mids = [_safe_float(row.get("mid"), 0) for row in group_rows if _safe_float(row.get("mid"), 0) > 0]
        lasts = [_safe_float(row.get("last"), 0) for row in group_rows if _safe_float(row.get("last"), 0) > 0]
        volumes = [_safe_float(row.get("volume"), 0) for row in group_rows]
        spreads = []
        weighted_price = 0.0
        total_volume = 0.0
        returns = []
        prev = None
        for row in group_rows:
            bid = _safe_float(row.get("bid"), 0)
            ask = _safe_float(row.get("ask"), 0)
            mid = _safe_float(row.get("mid"), 0)
            last = _safe_float(row.get("last"), 0)
            volume = max(0.0, _safe_float(row.get("volume"), 0))
            if mid > 0 and ask >= bid > 0:
                spreads.append(((ask - bid) / mid) * 10000)
            if last > 0 and volume > 0:
                weighted_price += last * volume
                total_volume += volume
            if prev and last > 0 and prev > 0:
                returns.append((last - prev) / prev)
            if last > 0:
                prev = last
        realized_vol = math.sqrt(sum(value * value for value in returns) / max(1, len(returns))) * math.sqrt(252) if returns else 0
        out_rows.append({
            group_by: key,
            "rows": len(group_rows),
            "vwap": round(weighted_price / total_volume, 6) if total_volume else 0,
            "avg_mid": round(sum(mids) / len(mids), 6) if mids else 0,
            "avg_last": round(sum(lasts) / len(lasts), 6) if lasts else 0,
            "total_volume": round(sum(volumes), 2),
            "avg_spread_bps": round(sum(spreads) / len(spreads), 4) if spreads else 0,
            "realized_volatility": round(realized_vol, 6),
            "liquidity_score": round((sum(volumes) / max(1, len(group_rows))) / max(1, (sum(spreads) / max(1, len(spreads))) or 1), 4),
        })
    out_rows.sort(key=lambda row: row.get("liquidity_score", 0), reverse=True)
    return {
        "ok": True,
        "mode": "COLUMNAR_TIME_PARTITIONED_MARKET_QUERY",
        "group_by": group_by,
        "symbol_filter": symbol_filter,
        "rows": out_rows[: max(1, min(500, _safe_int(spec.get("limit"), 50)))],
        "metadata": {"dataset_dir": str(dataset_dir), "query_horizon": spec.get("horizon", "INTRADAY_BAR"), "pre_aggregation_required": False},
        "orders_placed": False,
        "live_trading_changed": False,
    }


def version_market_data_adjustment(report_dir: Path, adjustment: Dict[str, Any]) -> Dict[str, Any]:
    adjustment_id = f"MDA-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    payload = {
        "ok": True,
        "adjustment_id": adjustment_id,
        "created_at": _now_iso(),
        "snapshot_version": adjustment.get("snapshot_version") or f"what_if_snapshot_{datetime.now().strftime('%Y%m%d')}",
        "adjustment": {
            "symbol": str(adjustment.get("symbol") or "").upper(),
            "field": str(adjustment.get("field") or ""),
            "old_value": adjustment.get("old_value", ""),
            "new_value": adjustment.get("new_value", ""),
            "reason": str(adjustment.get("reason") or "PMO what-if adjustment"),
            "owner": str(adjustment.get("owner") or "PMO_OWNER"),
        },
        "impact_mode": "WHAT_IF_ONLY",
        "original_data_mutated": False,
        "orders_placed": False,
        "live_trading_changed": False,
    }
    path = report_dir / f"pmo_market_data_adjustment_{adjustment_id}.json"
    _write_json(path, payload)
    payload["file"] = str(path)
    return payload


def explain_market_data_lineage(report_dir: Path, symbol: str = "") -> Dict[str, Any]:
    dataset_dir = _latest_dataset_dir(report_dir)
    quality = {}
    qpath = report_dir / "pmo_market_data_quality_latest.json"
    if qpath.exists():
        try:
            quality = json.loads(qpath.read_text(encoding="utf-8"))
        except Exception:
            quality = {}
    return {
        "ok": True,
        "mode": "MARKET_DATA_EXPLAINABILITY",
        "symbol": str(symbol or "ALL").upper(),
        "lineage": {
            "source": "synthetic_governed_market_data",
            "dataset_dir": str(dataset_dir) if dataset_dir else "",
            "table": "market_data.csv",
            "partition_keys": market_data_model()["partitions"],
            "quality_report": str(qpath),
            "snapshot_policy": "versioned snapshots; original rows remain immutable; adjustments are separate what-if records",
        },
        "quality_summary": {
            "status": quality.get("status", "NOT_RUN"),
            "row_count": quality.get("row_count", 0),
            "event_count": quality.get("event_count", 0),
            "critical_count": quality.get("critical_count", 0),
            "high_count": quality.get("high_count", 0),
        },
        "explainability": [
            "Every derived metric reports its source table and query horizon.",
            "Quality events identify rule id, severity, field, observed value, expected value, and explanation.",
            "What-if adjustments are versioned separately and do not overwrite official snapshots.",
            "Backtests and replays can cite snapshot_version for reproducibility.",
        ],
        "orders_placed": False,
        "live_trading_changed": False,
    }


def strategy_lab_status(report_dir: Path) -> Dict[str, Any]:
    dataset_dir = _latest_dataset_dir(report_dir)
    rows = _read_csv_rows(dataset_dir / "market_data.csv", limit=250000) if dataset_dir else []
    symbols = sorted({str(row.get("symbol", "")).upper() for row in rows if row.get("symbol")})
    timestamps = sorted(str(row.get("timestamp", "")) for row in rows if row.get("timestamp"))
    return {
        "ok": True,
        "mode": "PMO_STRATEGY_TESTER_RESEARCH_ONLY",
        "dataset_dir": str(dataset_dir) if dataset_dir else "",
        "market_data_rows": len(rows),
        "symbol_count": len(symbols),
        "symbols": symbols[:50],
        "history": {
            "oldest_timestamp": timestamps[0] if timestamps else "",
            "newest_timestamp": timestamps[-1] if timestamps else "",
            "fifty_year_ready": True,
            "current_loaded_history": "generated package sample" if rows else "no generated package",
        },
        "strategy_inputs": ["manual_rules", "natural_language", "ai_generated_template", "custom_indicator_js_metadata"],
        "supported_templates": ["VWAP_REVERSION", "MOMENTUM_BREAKOUT", "MEAN_REVERSION", "RVOL_VWAP_ALIGNMENT"],
        "market_conditions": list(MARKET_STRESS_PERIODS),
        "safety": {
            "research_only": True,
            "orders_placed": False,
            "live_trading_changed": False,
            "javascript_executed_server_side": False,
        },
    }


def _parse_ts(value: Any) -> datetime:
    text = str(value or "")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return datetime.min


def _strategy_from_prompt(prompt: str) -> Dict[str, Any]:
    text = str(prompt or "").lower()
    if "breakout" in text or "momentum" in text or "new high" in text:
        template = "MOMENTUM_BREAKOUT"
        params = {"lookback": 20, "rvol_mult": 1.4, "take_profit_pct": 0.035, "stop_loss_pct": 0.02, "max_hold_bars": 18}
    elif "mean" in text or "reversion" in text or "dip" in text or "oversold" in text:
        template = "MEAN_REVERSION"
        params = {"lookback": 18, "dip_pct": 0.012, "take_profit_pct": 0.025, "stop_loss_pct": 0.018, "max_hold_bars": 14}
    elif "rvol" in text or "volume" in text:
        template = "RVOL_VWAP_ALIGNMENT"
        params = {"lookback": 16, "rvol_mult": 1.5, "vwap_floor_bps": -100, "vwap_ceiling_bps": 50, "take_profit_pct": 0.03, "stop_loss_pct": 0.018, "max_hold_bars": 16}
    else:
        template = "VWAP_REVERSION"
        params = {"lookback": 20, "vwap_floor_bps": -125, "vwap_ceiling_bps": 50, "take_profit_pct": 0.028, "stop_loss_pct": 0.018, "max_hold_bars": 16}
    return {
        "name": prompt[:90] if prompt else template.replace("_", " ").title(),
        "template": template,
        "side": "LONG_ONLY",
        "parameters": params,
        "source": "natural_language",
        "prompt": prompt,
    }


def _normalize_strategy_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(spec, dict):
        spec = {}
    prompt = str(spec.get("natural_language") or spec.get("prompt") or "").strip()
    if prompt:
        strategy = _strategy_from_prompt(prompt)
    else:
        template = str(spec.get("template") or "VWAP_REVERSION").upper()
        if template not in {"VWAP_REVERSION", "MOMENTUM_BREAKOUT", "MEAN_REVERSION", "RVOL_VWAP_ALIGNMENT"}:
            template = "VWAP_REVERSION"
        strategy = _strategy_from_prompt(template)
        strategy["template"] = template
        strategy["source"] = "manual_rules"
        strategy["name"] = str(spec.get("name") or template.replace("_", " ").title())[:90]
    params = dict(strategy.get("parameters") or {})
    params.update({k: v for k, v in (spec.get("parameters") or {}).items() if v not in (None, "")})
    params["lookback"] = max(5, min(80, _safe_int(params.get("lookback"), 20)))
    params["max_hold_bars"] = max(2, min(120, _safe_int(params.get("max_hold_bars"), 16)))
    params["take_profit_pct"] = max(0.002, min(0.25, _safe_float(params.get("take_profit_pct"), 0.028)))
    params["stop_loss_pct"] = max(0.002, min(0.25, _safe_float(params.get("stop_loss_pct"), 0.018)))
    params["rvol_mult"] = max(0.5, min(5.0, _safe_float(params.get("rvol_mult"), 1.5)))
    params["dip_pct"] = max(0.001, min(0.15, _safe_float(params.get("dip_pct"), 0.012)))
    params["vwap_floor_bps"] = max(-1000, min(1000, _safe_float(params.get("vwap_floor_bps"), -125)))
    params["vwap_ceiling_bps"] = max(-1000, min(1000, _safe_float(params.get("vwap_ceiling_bps"), 50)))
    strategy["parameters"] = params
    if spec.get("custom_indicator_js"):
        strategy["custom_indicator_js_metadata"] = {
            "accepted": True,
            "server_side_execution": False,
            "reason": "JavaScript indicators are stored as research metadata only until explicitly sandboxed and allowlisted.",
            "length": len(str(spec.get("custom_indicator_js") or "")),
        }
    return strategy


def _condition_for_bar(row: Dict[str, Any], returns: List[float]) -> str:
    vol = _safe_float(row.get("volatility"), 0)
    if vol >= 0.45:
        return "HIGH_VOL"
    if len(returns) >= 6:
        recent = sum(returns[-6:])
        if abs(recent) < 0.004:
            return "CHOP"
        return "TREND_UP" if recent > 0 else "TREND_DOWN"
    return "NORMAL"


def _entry_signal(template: str, price: float, prev_prices: List[float], volume: float, prev_volumes: List[float], vwap: float, params: Dict[str, Any]) -> bool:
    if price <= 0 or len(prev_prices) < max(2, _safe_int(params.get("lookback"), 20) // 2):
        return False
    sma = sum(prev_prices) / len(prev_prices)
    avg_volume = sum(prev_volumes) / len(prev_volumes) if prev_volumes else 0
    rvol_ok = volume >= avg_volume * _safe_float(params.get("rvol_mult"), 1.5) if avg_volume > 0 else True
    if template == "MOMENTUM_BREAKOUT":
        return price > max(prev_prices) and rvol_ok
    if template == "MEAN_REVERSION":
        return price < sma * (1.0 - _safe_float(params.get("dip_pct"), 0.012))
    if template == "RVOL_VWAP_ALIGNMENT":
        if vwap <= 0 or not rvol_ok:
            return False
        dist_bps = ((price - vwap) / vwap) * 10000
        return _safe_float(params.get("vwap_floor_bps"), -100) <= dist_bps <= _safe_float(params.get("vwap_ceiling_bps"), 50)
    if vwap <= 0:
        return False
    dist_bps = ((price - vwap) / vwap) * 10000
    return _safe_float(params.get("vwap_floor_bps"), -125) <= dist_bps <= _safe_float(params.get("vwap_ceiling_bps"), 50)


def run_strategy_backtest(report_dir: Path, spec: Dict[str, Any]) -> Dict[str, Any]:
    dataset_dir = _latest_dataset_dir(report_dir)
    if not dataset_dir:
        return {"ok": False, "error": "No generated financial dataset package found.", "orders_placed": False, "live_trading_changed": False}
    rows = _read_csv_rows(dataset_dir / "market_data.csv")
    if not rows:
        return {"ok": False, "error": "market_data.csv has no rows.", "orders_placed": False, "live_trading_changed": False}
    strategy = _normalize_strategy_spec(spec)
    symbol_filter = str(spec.get("symbol") or "").upper().strip()
    max_symbols = max(1, min(50, _safe_int(spec.get("max_symbols"), 10)))
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        symbol = str(row.get("symbol", "")).upper()
        if not symbol or (symbol_filter and symbol != symbol_filter):
            continue
        by_symbol.setdefault(symbol, []).append(row)
    selected_symbols = sorted(by_symbol)[:max_symbols]
    params = strategy.get("parameters", {})
    template = str(strategy.get("template", "VWAP_REVERSION"))
    trades: List[Dict[str, Any]] = []
    condition_summary: Dict[str, Dict[str, Any]] = {}
    for symbol in selected_symbols:
        series = sorted(by_symbol[symbol], key=lambda row: _parse_ts(row.get("timestamp")))
        if len(series) < _safe_int(params.get("lookback"), 20) + 3:
            continue
        price_window: List[float] = []
        volume_window: List[float] = []
        returns: List[float] = []
        weighted_price = 0.0
        total_volume = 0.0
        position: Optional[Dict[str, Any]] = None
        prev_price = 0.0
        for idx, row in enumerate(series):
            price = _safe_float(row.get("last"), 0)
            volume = max(0.0, _safe_float(row.get("volume"), 0))
            if price <= 0:
                continue
            if prev_price > 0:
                returns.append((price - prev_price) / prev_price)
            weighted_price += price * max(1.0, volume)
            total_volume += max(1.0, volume)
            vwap = weighted_price / total_volume if total_volume else price
            condition = _condition_for_bar(row, returns)
            spread_bps = 0.0
            bid = _safe_float(row.get("bid"), 0)
            ask = _safe_float(row.get("ask"), 0)
            mid = _safe_float(row.get("mid"), price)
            if ask >= bid > 0 and mid > 0:
                spread_bps = ((ask - bid) / mid) * 10000
            if position:
                bars_held = idx - position["entry_idx"]
                gross_return = (price - position["entry_price"]) / position["entry_price"]
                exit_reason = ""
                if gross_return >= _safe_float(params.get("take_profit_pct"), 0.028):
                    exit_reason = "TAKE_PROFIT"
                elif gross_return <= -_safe_float(params.get("stop_loss_pct"), 0.018):
                    exit_reason = "STOP_LOSS"
                elif bars_held >= _safe_int(params.get("max_hold_bars"), 16):
                    exit_reason = "TIME_EXIT"
                elif template == "MEAN_REVERSION" and price >= (sum(price_window) / len(price_window) if price_window else price):
                    exit_reason = "MEAN_REVERSION_EXIT"
                if exit_reason:
                    round_trip_cost = (position.get("entry_spread_bps", 0.0) + spread_bps) / 10000.0
                    net_return = gross_return - round_trip_cost
                    trade = {
                        "symbol": symbol,
                        "entry_time": position["entry_time"],
                        "exit_time": row.get("timestamp", ""),
                        "entry_price": round(position["entry_price"], 6),
                        "exit_price": round(price, 6),
                        "bars_held": bars_held,
                        "gross_return_pct": round(gross_return * 100, 4),
                        "net_return_pct": round(net_return * 100, 4),
                        "exit_reason": exit_reason,
                        "market_condition": position.get("market_condition", condition),
                        "vwap_at_entry": round(position.get("vwap", 0), 6),
                        "entry_spread_bps": round(position.get("entry_spread_bps", 0), 4),
                    }
                    trades.append(trade)
                    bucket = condition_summary.setdefault(trade["market_condition"], {"trades": 0, "wins": 0, "net_return_pct": 0.0})
                    bucket["trades"] += 1
                    bucket["wins"] += 1 if net_return > 0 else 0
                    bucket["net_return_pct"] += net_return * 100
                    position = None
            if not position and price_window:
                if _entry_signal(template, price, price_window, volume, volume_window, vwap, params):
                    position = {
                        "entry_idx": idx,
                        "entry_time": row.get("timestamp", ""),
                        "entry_price": price,
                        "entry_spread_bps": spread_bps,
                        "market_condition": condition,
                        "vwap": vwap,
                    }
            price_window.append(price)
            volume_window.append(volume)
            lookback = _safe_int(params.get("lookback"), 20)
            if len(price_window) > lookback:
                price_window.pop(0)
            if len(volume_window) > lookback:
                volume_window.pop(0)
            prev_price = price
    wins = [trade for trade in trades if _safe_float(trade.get("net_return_pct"), 0) > 0]
    losses = [trade for trade in trades if _safe_float(trade.get("net_return_pct"), 0) <= 0]
    gross_profit = sum(_safe_float(trade.get("net_return_pct"), 0) for trade in wins)
    gross_loss = abs(sum(_safe_float(trade.get("net_return_pct"), 0) for trade in losses))
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for trade in trades:
        equity += _safe_float(trade.get("net_return_pct"), 0)
        peak = max(peak, equity)
        max_dd = min(max_dd, equity - peak)
    for bucket in condition_summary.values():
        bucket["win_rate"] = round(bucket["wins"] / bucket["trades"], 4) if bucket["trades"] else 0
        bucket["net_return_pct"] = round(bucket["net_return_pct"], 4)
    result = {
        "ok": True,
        "mode": "STRATEGY_BACKTEST_RESEARCH_ONLY",
        "strategy": strategy,
        "symbols_tested": selected_symbols,
        "metrics": {
            "trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(trades), 4) if trades else 0,
            "profit_factor": round(gross_profit / gross_loss, 4) if gross_loss else (round(gross_profit, 4) if gross_profit else 0),
            "net_return_pct": round(sum(_safe_float(trade.get("net_return_pct"), 0) for trade in trades), 4),
            "avg_win_pct": round(gross_profit / len(wins), 4) if wins else 0,
            "avg_loss_pct": round(-gross_loss / len(losses), 4) if losses else 0,
            "max_drawdown_pct": round(max_dd, 4),
            "avg_hold_bars": round(sum(_safe_float(trade.get("bars_held"), 0) for trade in trades) / len(trades), 2) if trades else 0,
        },
        "market_condition_breakdown": condition_summary,
        "sample_trades": trades[:25],
        "data_governance": {
            "dataset_dir": str(dataset_dir),
            "snapshot_policy": "reproducible generated package; no pre-aggregation required",
            "history_note": "Use larger imported history packages for multi-decade research.",
        },
        "orders_placed": False,
        "live_trading_changed": False,
        "research_only": True,
    }
    _write_json(report_dir / "pmo_strategy_backtest_latest.json", result)
    return result


def optimize_strategy(report_dir: Path, spec: Dict[str, Any]) -> Dict[str, Any]:
    base = _normalize_strategy_spec(spec)
    template = base.get("template", "VWAP_REVERSION")
    candidates: List[Dict[str, Any]] = []
    if template == "MOMENTUM_BREAKOUT":
        grid = [{"lookback": lb, "rvol_mult": rv} for lb in (12, 20, 32) for rv in (1.2, 1.5, 2.0)]
    elif template == "MEAN_REVERSION":
        grid = [{"lookback": lb, "dip_pct": dip} for lb in (12, 18, 28) for dip in (0.008, 0.012, 0.02)]
    else:
        grid = [{"lookback": lb, "vwap_floor_bps": floor, "vwap_ceiling_bps": 50} for lb in (12, 20, 32) for floor in (-200, -125, -75)]
    for params in grid:
        run_spec = dict(spec or {})
        merged = dict(base.get("parameters") or {})
        merged.update(params)
        run_spec["template"] = template
        run_spec["parameters"] = merged
        result = run_strategy_backtest(report_dir, run_spec)
        metrics = result.get("metrics", {}) if result.get("ok") else {}
        candidates.append({
            "template": template,
            "parameters": merged,
            "trades": metrics.get("trades", 0),
            "win_rate": metrics.get("win_rate", 0),
            "profit_factor": metrics.get("profit_factor", 0),
            "net_return_pct": metrics.get("net_return_pct", 0),
            "max_drawdown_pct": metrics.get("max_drawdown_pct", 0),
        })
    candidates.sort(key=lambda row: (_safe_float(row.get("profit_factor"), 0), _safe_float(row.get("net_return_pct"), 0), _safe_float(row.get("win_rate"), 0)), reverse=True)
    result = {
        "ok": True,
        "mode": "STRATEGY_OPTIMIZATION_RESEARCH_ONLY",
        "base_strategy": base,
        "candidate_count": len(candidates),
        "best": candidates[0] if candidates else {},
        "candidates": candidates,
        "guardrail": "Optimization is research-only. Do not raise execution confidence until validated on out-of-sample data.",
        "orders_placed": False,
        "live_trading_changed": False,
        "research_only": True,
    }
    _write_json(report_dir / "pmo_strategy_optimization_latest.json", result)
    return result


def generate_ai_strategy_template(report_dir: Path, spec: Dict[str, Any]) -> Dict[str, Any]:
    prompt = str((spec or {}).get("natural_language") or (spec or {}).get("desired_outcome") or "VWAP pullback with volume confirmation")
    strategy = _strategy_from_prompt(prompt)
    strategy["source"] = "pmo_ai_template_generator"
    strategy["ml_model_status"] = {
        "true_ml_training_ready": True,
        "trained_now": False,
        "reason": "This endpoint creates a governed strategy specification. Model training requires approved feature store and out-of-sample validation.",
        "features": ["vwap_distance_bps", "relative_volume", "realized_volatility", "spread_bps", "market_condition"],
    }
    result = {
        "ok": True,
        "mode": "AI_STRATEGY_TEMPLATE_RESEARCH_ONLY",
        "strategy": strategy,
        "next_step": "Run /api/financial-dataset/strategy/backtest, then optimize, then validate on a separate snapshot.",
        "orders_placed": False,
        "live_trading_changed": False,
        "research_only": True,
    }
    _write_json(report_dir / "pmo_ai_strategy_template_latest.json", result)
    return result
