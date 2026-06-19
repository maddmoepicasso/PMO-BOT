"""PMO Strategy Knowledge Pack.

Read-only trading education layer for PMO Bot. This module turns high-probability
setup concepts into structured checks that can be used by PMO AI, Why-Not, the
trade discipline panel, and research/backtest tooling. It does not place orders,
unlock live trading, or modify settings.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


PMO_STRATEGY_KNOWLEDGE_VERSION = "pmo_strategy_knowledge_v1"


INSTITUTIONAL_STRATEGY_ROWS = [
    ("50/200 EMA Trend Following", 1, "Very Easy", "trend_following"),
    ("Donchian Channel Breakout", 1, "Very Easy", "breakout"),
    ("Turtle Trading", 1, "Very Easy", "trend_following"),
    ("Moving Average Ribbon", 1, "Very Easy", "trend_following"),
    ("Dual Momentum", 1, "Very Easy", "momentum"),
    ("RSI Mean Reversion", 1, "Very Easy", "mean_reversion"),
    ("Bollinger Band Mean Reversion", 1, "Very Easy", "mean_reversion"),
    ("Keltner Channel Breakout", 1, "Very Easy", "breakout"),
    ("MACD Momentum", 1, "Very Easy", "momentum"),
    ("ADX Trend Strength Filter", 1, "Very Easy", "regime_filter"),
    ("Volatility-Adjusted Trend Following", 2, "Easy", "trend_following"),
    ("ATR Breakout", 2, "Easy", "breakout"),
    ("Opening Range Breakout", 2, "Easy", "breakout"),
    ("VWAP Trend Following", 2, "Easy", "trend_following"),
    ("VWAP Mean Reversion", 2, "Easy", "mean_reversion"),
    ("Relative Strength Rotation", 2, "Easy", "rotation"),
    ("Sector Momentum Rotation", 2, "Easy", "rotation"),
    ("Time-Series Momentum", 2, "Easy", "momentum"),
    ("Cross-Asset Momentum", 2, "Easy", "cross_asset"),
    ("Multi-Timeframe Trend Alignment", 2, "Easy", "trend_following"),
    ("Volatility Targeting", 3, "Intermediate", "risk_management"),
    ("Dynamic Position Sizing", 3, "Intermediate", "risk_management"),
    ("Risk-Parity Portfolio", 3, "Intermediate", "portfolio"),
    ("Equal-Risk Contribution", 3, "Intermediate", "portfolio"),
    ("Adaptive Moving Average Systems", 3, "Intermediate", "adaptive"),
    ("Regime Detection Models", 3, "Intermediate", "regime_model"),
    ("Trend + Mean Reversion Switching", 3, "Intermediate", "regime_switching"),
    ("Market Breadth Models", 3, "Intermediate", "breadth"),
    ("Advance/Decline Momentum", 3, "Intermediate", "breadth"),
    ("Volatility Expansion Systems", 3, "Intermediate", "volatility"),
    ("Pairs Trading", 4, "Advanced", "stat_arb"),
    ("Cointegration Trading", 4, "Advanced", "stat_arb"),
    ("Statistical Arbitrage", 4, "Advanced", "stat_arb"),
    ("Index Arbitrage", 4, "Advanced", "arbitrage"),
    ("Futures Calendar Spread Trading", 4, "Advanced", "spread"),
    ("Intermarket Spread Trading", 4, "Advanced", "spread"),
    ("Yield Curve Trading", 4, "Advanced", "rates"),
    ("Cross-Asset Relative Value", 4, "Advanced", "relative_value"),
    ("Volatility Carry", 4, "Advanced", "carry"),
    ("Futures Carry Strategy", 4, "Advanced", "carry"),
    ("Global Macro Systematic", 5, "Institutional Quant", "macro"),
    ("Factor Investing (Value + Momentum)", 5, "Institutional Quant", "factor"),
    ("Smart Beta Rotation", 5, "Institutional Quant", "factor"),
    ("Multi-Factor Equity Models", 5, "Institutional Quant", "factor"),
    ("CTA Portfolio Replication", 5, "Institutional Quant", "cta"),
    ("Adaptive Risk-Parity + Trend", 5, "Institutional Quant", "portfolio"),
    ("Alternative Data Models", 5, "Institutional Quant", "alternative_data"),
    ("Machine Learning Classification Models", 5, "Institutional Quant", "machine_learning"),
    ("Reinforcement Learning Trading Systems", 5, "Institutional Quant", "reinforcement_learning"),
    ("High-Frequency Market Making", 5, "Institutional Quant", "market_making"),
]


TRADINGVIEW_STRATEGY_ROWS = [
    ("50 EMA / 200 EMA Golden Cross", "Trend Following"),
    ("20 EMA Pullback Trend Strategy", "Trend Following"),
    ("9 EMA / 21 EMA Crossover", "Trend Following"),
    ("Triple Moving Average Alignment", "Trend Following"),
    ("Supertrend Trend Following", "Trend Following"),
    ("Donchian Channel Trend Following", "Trend Following"),
    ("ADX + Moving Average Trend Filter", "Trend Following"),
    ("Gaussian Channel Trend Strategy", "Trend Following"),
    ("Hull Moving Average Trend Strategy", "Trend Following"),
    ("Long-Term Turtle Trading System", "Trend Following"),
    ("Opening Range Breakout", "Breakout"),
    ("Donchian Channel Breakout", "Breakout"),
    ("Bollinger Band Squeeze Breakout", "Breakout"),
    ("Volatility Expansion Breakout", "Breakout"),
    ("Trendline Breakout", "Breakout"),
    ("Support Resistance Breakout", "Breakout"),
    ("Consolidation Box Breakout", "Breakout"),
    ("High-of-Day Breakout", "Breakout"),
    ("52-Week High Breakout", "Breakout"),
    ("ATR Breakout Strategy", "Breakout"),
    ("RSI(2) Mean Reversion", "Mean Reversion"),
    ("RSI Oversold Bounce", "Mean Reversion"),
    ("Bollinger Band Reversion", "Mean Reversion"),
    ("VWAP Reversion", "Mean Reversion"),
    ("Keltner Channel Reversion", "Mean Reversion"),
    ("Gap Fill Strategy", "Mean Reversion"),
    ("Three Red Candles Reversal", "Mean Reversion"),
    ("Extreme Deviation Reversion", "Mean Reversion"),
    ("Z-Score Mean Reversion", "Mean Reversion"),
    ("Moving Average Reversion Strategy", "Mean Reversion"),
    ("MACD Crossover", "Momentum"),
    ("RSI + MACD Confirmation", "Momentum"),
    ("Stochastic Momentum Strategy", "Momentum"),
    ("Momentum Ignition Breakout", "Momentum"),
    ("Relative Strength Rotation", "Momentum"),
    ("Rate of Change (ROC) Strategy", "Momentum"),
    ("Price Momentum Ranking", "Momentum"),
    ("Volume + Momentum Confirmation", "Momentum"),
    ("Multi-Timeframe Momentum", "Momentum"),
    ("Trend + Momentum Hybrid", "Momentum"),
    ("Volume Spike Reversal", "Volume"),
    ("OBV Trend Confirmation", "Volume"),
    ("VWAP Trend Strategy", "Volume"),
    ("Accumulation/Distribution Breakout", "Volume"),
    ("High Relative Volume Momentum", "Volume"),
    ("EMA + RSI + Volume Filter", "Advanced / Hybrid"),
    ("ADX Regime Switching Strategy", "Advanced / Hybrid"),
    ("Breakout + Pullback + Momentum System", "Advanced / Hybrid"),
    ("Trend Following + Mean Reversion Hybrid", "Advanced / Hybrid"),
    ("AI Regime Adaptive Strategy", "Advanced / Hybrid"),
]


HIGHEST_PROBABILITY_INSTITUTIONAL = [
    "Time-Series Momentum",
    "Trend Following CTA",
    "Donchian Breakouts",
    "Risk-Parity + Trend",
    "Volatility Targeting",
    "Relative Strength Rotation",
    "Futures Carry",
    "Cross-Asset Momentum",
    "Sector Rotation",
    "Statistical Arbitrage",
]


PMO_STRATEGY_COVERAGE_KEYWORDS = {
    "ACTIVE": [
        "ema", "moving average", "macd", "rsi", "bollinger", "keltner", "atr",
        "opening range", "vwap", "relative strength", "sector momentum",
        "multi-timeframe", "regime", "market breadth", "volatility expansion",
        "dynamic position sizing", "volatility targeting", "machine learning",
        "reinforcement learning", "ai regime", "volume", "rvol",
    ],
    "PARTIAL": [
        "donchian", "turtle", "dual momentum", "cross-asset", "risk-parity",
        "equal-risk", "factor", "smart beta", "cta", "pairs", "statistical arbitrage",
        "z-score", "gap fill", "support resistance", "trendline", "52-week",
    ],
    "RESEARCH_ONLY": [
        "futures", "yield curve", "carry", "calendar spread", "intermarket",
        "index arbitrage", "high-frequency", "market making", "alternative data",
        "global macro", "relative value",
    ],
}


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _clean_text(value).upper()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except Exception:
        return default


def _has_any(row: Dict[str, Any], keys: List[str]) -> bool:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", "None", "nan", "NaN"):
            return True
    return False


def _slug(value: Any) -> str:
    cleaned = _clean_text(value).lower()
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in cleaned)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "strategy"


def _coverage_status(name: str) -> str:
    lowered = name.lower()
    for status in ("RESEARCH_ONLY", "ACTIVE", "PARTIAL"):
        if any(keyword in lowered for keyword in PMO_STRATEGY_COVERAGE_KEYWORDS[status]):
            return status
    return "TODO"


def _strategy_notes(status: str) -> str:
    if status == "ACTIVE":
        return "PMO already has related signal, filter, risk, or intelligence components. Still requires walk-forward proof before live use."
    if status == "PARTIAL":
        return "PMO has adjacent data or logic, but this exact strategy needs a dedicated template and backtest report."
    if status == "RESEARCH_ONLY":
        return "Institutional concept recorded for research. Execution remains blocked until data, broker support, costs, and risk model exist."
    return "Cataloged idea. Needs Pine/Python template, historical data, and validation before PMO can use it."


def pmo_strategy_catalog_snapshot(max_rows: Optional[int] = None) -> Dict[str, Any]:
    """Return PMO's read-only catalog of institutional and TradingView strategy ideas."""
    institutional_rows: List[Dict[str, Any]] = []
    for index, (name, tier, difficulty, family) in enumerate(INSTITUTIONAL_STRATEGY_ROWS, start=1):
        status = _coverage_status(name)
        institutional_rows.append({
            "rank": index,
            "id": "inst_" + _slug(name),
            "name": name,
            "catalog": "institutional",
            "tier": tier,
            "difficulty": difficulty,
            "family": family,
            "implementation_status": status,
            "automation": "TRADINGVIEW_READY" if tier <= 2 else "PYTHON_RESEARCH" if tier <= 4 else "INSTITUTIONAL_RESEARCH",
            "research_only": True,
            "orders_placed": False,
            "live_unlocked": False,
            "notes": _strategy_notes(status),
        })

    tradingview_rows: List[Dict[str, Any]] = []
    for index, (name, category) in enumerate(TRADINGVIEW_STRATEGY_ROWS, start=1):
        status = _coverage_status(name)
        tradingview_rows.append({
            "rank": index,
            "id": "tv_" + _slug(name),
            "name": name,
            "catalog": "tradingview",
            "category": category,
            "tier": 1 if index <= 20 else 2 if index <= 45 else 3,
            "difficulty": "TradingView Ready" if index <= 45 else "Hybrid",
            "family": _slug(category),
            "implementation_status": status,
            "automation": "PINE_TEMPLATE_READY" if index <= 45 else "PINE_PLUS_PYTHON",
            "research_only": True,
            "orders_placed": False,
            "live_unlocked": False,
            "notes": _strategy_notes(status),
        })

    rows = institutional_rows + tradingview_rows
    if max_rows is not None:
        rows = rows[: max(0, int(max_rows))]

    status_counts: Dict[str, int] = {}
    family_counts: Dict[str, int] = {}
    for row in institutional_rows + tradingview_rows:
        status_counts[row["implementation_status"]] = status_counts.get(row["implementation_status"], 0) + 1
        family_counts[row["family"]] = family_counts.get(row["family"], 0) + 1

    return {
        "ok": True,
        "version": PMO_STRATEGY_KNOWLEDGE_VERSION,
        "name": "PMO Institutional + TradingView Strategy Catalog",
        "mode": "READ_ONLY_RESEARCH_CATALOG",
        "research_only": True,
        "orders_placed": False,
        "live_unlocked": False,
        "total": len(institutional_rows) + len(tradingview_rows),
        "institutional_total": len(institutional_rows),
        "tradingview_total": len(tradingview_rows),
        "status_counts": status_counts,
        "family_counts": family_counts,
        "highest_probability_institutional": HIGHEST_PROBABILITY_INSTITUTIONAL,
        "recommended_validation": {
            "minimum_trades": 2000,
            "symbols": ["SPY", "QQQ", "ES", "NQ", "BTCUSD", "ETHUSD", "EURUSD", "GC"],
            "timeframes": ["5m", "15m", "1H", "4H", "1D"],
            "metrics": ["win_rate", "profit_factor", "expectancy", "sharpe", "sortino", "max_drawdown", "calmar", "cagr"],
            "controls": ["walk_forward", "monte_carlo", "realistic_commissions", "realistic_slippage", "overfit_check"],
        },
        "portfolio_prompt_summary": "Backtest the top institutional strategy families with volatility targeting, risk parity sizing, walk-forward validation, Monte Carlo simulation, realistic costs, and dynamic regime allocation across trend, momentum, carry, and stat-arb.",
        "rows": rows,
    }


def high_probability_setup_knowledge() -> Dict[str, Any]:
    """Return PMO's structured high-probability setup framework."""
    return {
        "ok": True,
        "version": PMO_STRATEGY_KNOWLEDGE_VERSION,
        "name": "PMO High-Probability Setup Framework",
        "mode": "RESEARCH_AND_DISCIPLINE",
        "research_only": True,
        "score_boost_enabled": False,
        "live_unlocked": False,
        "orders_placed": False,
        "principles": [
            {
                "id": "clear_market_structure",
                "name": "Clear market structure",
                "rule": "Prefer trades with visible directional structure, such as higher highs/higher lows for longs or lower highs/lower lows for shorts.",
                "data_fields": ["trend", "market_structure", "higher_highs", "higher_lows", "lower_highs", "lower_lows"],
            },
            {
                "id": "institutional_confluence",
                "name": "Institutional confluence",
                "rule": "Require multiple independent reasons at the same price area before treating a setup as trade-ready.",
                "data_fields": ["vwap", "ema_alignment", "fib_level", "fair_value_gap", "support_resistance", "relative_volume"],
            },
            {
                "id": "liquidity_grab_then_shift",
                "name": "Liquidity grab plus structure shift",
                "rule": "A stop-run or liquidity sweep is not enough by itself; PMO should wait for a structural shift before classifying it as a reversal setup.",
                "data_fields": ["liquidity_grab", "swing_high_sweep", "swing_low_sweep", "structure_shift", "break_of_structure"],
            },
            {
                "id": "strict_risk_management",
                "name": "Strict risk management",
                "rule": "Every approved trade needs a logical stop, target, and account-scaled risk cap before entry.",
                "data_fields": ["stop_loss", "take_profit", "risk_reward", "risk_pct", "notional"],
            },
            {
                "id": "predefined_exits",
                "name": "Predefined exits",
                "rule": "Targets, stop levels, trailing activation, and partial exits should be known before the order is submitted.",
                "data_fields": ["exit_plan", "trailing_activation_profit_pct", "partial_exit_plan"],
            },
        ],
        "strategy_families": [
            {
                "id": "fib_retracement_confluence",
                "name": "Fibonacci retracement confluence",
                "entry_logic": "Trade pullbacks in the macro trend when price reaches a discount/premium level near a major retracement and a second confirmation agrees.",
                "required_data": ["fib_level", "trend", "support_resistance", "volume_or_vwap"],
            },
            {
                "id": "trend_following_pullback",
                "name": "Trend-following pullback",
                "entry_logic": "Enter in the direction of an established trend after a controlled pullback to EMA/VWAP/support, not after a chased extension.",
                "required_data": ["trend", "ema_alignment", "vwap_distance_pct", "relative_volume"],
            },
            {
                "id": "reversal_at_key_level",
                "name": "Reversal at key level",
                "entry_logic": "Consider reversals only after a liquidity grab at a key level and a confirmed shift in structure.",
                "required_data": ["liquidity_grab", "key_level", "structure_shift", "risk_defined"],
            },
            {
                "id": "mean_reversion",
                "name": "Mean reversion",
                "entry_logic": "Use RSI/Bollinger/multi-timeframe extension to identify stretched conditions likely to return toward VWAP or the moving average.",
                "required_data": ["rsi", "bollinger_position", "vwap_distance_pct", "multi_timeframe_context"],
            },
        ],
        "execution_rules": [
            "Do not approve a trade from one chart pattern alone.",
            "Require at least two independent confirmations before a setup becomes trade-ready.",
            "Use low scores and weak confluence for discovery only, not execution.",
            "A liquidity grab requires a confirmed structure shift before PMO treats it as a reversal.",
            "Stops, targets, and risk/reward must exist before entry.",
            "Keep live trading locked until paper proof validates the setup family.",
        ],
    }


def pmo_strategy_knowledge_summary(max_items: int = 4) -> Dict[str, Any]:
    pack = high_probability_setup_knowledge()
    return {
        "version": pack["version"],
        "mode": pack["mode"],
        "research_only": True,
        "score_boost_enabled": False,
        "principles": pack["principles"][:max_items],
        "strategy_families": pack["strategy_families"][:max_items],
        "execution_rules": pack["execution_rules"][:max_items],
        "live_unlocked": False,
        "orders_placed": False,
    }


def pmo_broker_guide_knowledge(source_url: str = "https://www.investing.com/brokers/guides/") -> Dict[str, Any]:
    """Return summarized broker/trading-guide decision rules for PMO.

    This is a summary framework, not a copy of the source articles.
    """
    return {
        "ok": True,
        "version": PMO_STRATEGY_KNOWLEDGE_VERSION,
        "name": "PMO Broker and Market Guide Framework",
        "source_url": source_url,
        "source_scope": "Summarized from public broker-guide categories covering brokers, forex, CFDs, crypto, stocks, ETFs, trading platforms, prop trading, fees, regulation, and risk disclosure.",
        "research_only": True,
        "score_boost_enabled": False,
        "live_unlocked": False,
        "orders_placed": False,
        "broker_selection_rules": [
            "Match the broker/data provider to the asset class before enabling paper or live execution.",
            "Verify account permissions for each asset class: stocks, ETFs, crypto, options, forex, CFDs, futures, and bonds are not interchangeable.",
            "Treat commission-free as not automatically free; spreads, payment for order flow, exchange fees, slippage, borrowing fees, and data fees still matter.",
            "Prefer regulated, transparent brokers for any real-money path; unsupported or weakly governed venues stay research-only.",
            "Use demo or paper validation before raising confidence in a broker route, asset class, or strategy.",
        ],
        "asset_class_decision_rules": [
            {"asset_class": "STOCK_OR_ETF", "pmo_rule": "Alpaca paper route allowed only after market data, spread, liquidity, PDT, and buying-power checks pass."},
            {"asset_class": "CRYPTO", "pmo_rule": "Crypto stays research/paper gated until volatility, exchange, spread, custody, and regulatory risk are explicitly handled."},
            {"asset_class": "FOREX_OR_CFD", "pmo_rule": "Keep scan-only unless PMO has a broker adapter, leverage policy, margin model, and jurisdiction/regulatory review."},
            {"asset_class": "FUTURES_OR_COMMODITIES", "pmo_rule": "Keep scan-only until contract specs, tick value, margin, session hours, and data feed are modeled."},
            {"asset_class": "BONDS_OR_FIXED_INCOME", "pmo_rule": "Research-only unless PMO has pricing, liquidity, duration, and broker capability checks."},
            {"asset_class": "PROP_TRADING", "pmo_rule": "Do not treat prop-style rules as live account readiness; model challenge rules separately from broker execution."},
        ],
        "risk_decision_rules": [
            "Margin and leverage increase financial risk and should tighten sizing, not increase confidence.",
            "External web prices can be delayed, indicative, or different from executable broker prices; broker-confirmed market data remains the execution authority.",
            "Do not use guide content or broker marketing as proof of strategy edge.",
            "Before any live route, PMO must know costs, slippage, market hours, liquidity, tax/reporting burden, and account restrictions.",
            "If broker/data reliability is unknown, PMO should block execution and keep the signal in research or watchlist mode.",
        ],
        "pmo_decision_impact": {
            "watchlist": "Can classify symbols and asset classes by broker/data readiness.",
            "why_not": "Can add warnings when asset permissions, data reliability, fees, leverage, or regulatory context are incomplete.",
            "execution": "Does not unlock live trading or lower score gates.",
            "learning": "Stores broker and market structure as context for post-trade analysis.",
        },
    }


def pmo_strategy_confluence_check(row: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Evaluate a signal row against the PMO high-probability setup framework."""
    settings = settings or {}
    row = row or {}
    confirmations: List[str] = []
    confirmation_sources: List[str] = []
    warnings: List[str] = []
    blockers: List[str] = []

    symbol = _upper(row.get("symbol"))
    bias = _upper(row.get("bias") or row.get("direction") or row.get("side"))
    trend = _upper(row.get("trend") or row.get("trend_direction") or row.get("market_structure"))
    regime = _upper(row.get("market_regime") or row.get("regime"))
    rvol = _float(row.get("relative_volume") or row.get("rvol"), 0.0)
    rsi = _float(row.get("rsi"), 0.0)
    risk_reward = _float(row.get("risk_reward") or row.get("rr") or row.get("risk_reward_ratio"), 0.0)
    required_confluence = int(max(1, _float(settings.get("PMO_STRATEGY_MIN_CONFLUENCE_COUNT", 2), 2)))

    wants_long = bias in {"CALL_BIAS", "BULLISH", "LONG", "BUY", "BUY_LONG"}
    wants_short = bias in {"PUT_BIAS", "BEARISH", "SHORT", "SELL", "SELL_SHORT"}

    trend_bullish = trend in {"UP", "UPTREND", "BULL", "BULLISH", "HIGHER_HIGHER_LOW", "HHHL", "HIGHER_HIGHS_HIGHER_LOWS"}
    trend_bearish = trend in {"DOWN", "DOWNTREND", "BEAR", "BEARISH", "LOWER_HIGH_LOWER_LOW", "LHLL", "LOWER_HIGHS_LOWER_LOWS"}
    if (wants_long and trend_bullish) or (wants_short and trend_bearish):
        confirmations.append("clear market structure confirms trade direction")
        confirmation_sources.append("market_structure")
    elif trend:
        warnings.append(f"strategy: market structure {trend} does not clearly confirm {bias or 'direction'}")
    else:
        warnings.append("strategy: market structure missing")

    if _has_any(row, ["ema_alignment", "ema_vwap_alignment", "vwap_alignment", "vwap_status", "support_resistance", "key_level"]):
        confirmations.append("technical confluence present near decision area")
        confirmation_sources.append("technical_confluence")
    if _has_any(row, ["fib_level", "fibonacci_level", "fib_retracement_pct", "fair_value_gap", "fvg"]):
        confirmations.append("institutional confluence field present")
        confirmation_sources.append("institutional_confluence")
    if rvol >= _float(settings.get("PMO_WHY_NOT_MIN_RVOL", 1.5), 1.5):
        confirmations.append(f"relative volume confirms participation ({rvol:g})")
        confirmation_sources.append("relative_volume")
    elif rvol > 0:
        warnings.append(f"strategy: relative volume {rvol:g} is weak for high-probability setup")

    liquidity_grab = bool(row.get("liquidity_grab") or row.get("liquidity_sweep") or row.get("swing_high_sweep") or row.get("swing_low_sweep"))
    structure_shift = bool(row.get("structure_shift") or row.get("break_of_structure") or row.get("bos") or row.get("change_of_character"))
    if liquidity_grab and structure_shift:
        confirmations.append("liquidity grab followed by structure shift")
        confirmation_sources.append("liquidity_shift")
    elif liquidity_grab:
        warnings.append("strategy: liquidity grab detected without confirmed structure shift")

    if rsi:
        if wants_long and rsi <= 40:
            confirmations.append(f"mean-reversion RSI support ({rsi:g})")
            confirmation_sources.append("mean_reversion")
        elif wants_short and rsi >= 60:
            confirmations.append(f"mean-reversion RSI resistance ({rsi:g})")
            confirmation_sources.append("mean_reversion")
        elif rsi >= 70 or rsi <= 30:
            warnings.append(f"strategy: RSI {rsi:g} is stretched; verify entry timing")

    has_stop = _has_any(row, ["stop_loss", "stop_loss_price", "stop", "stop_price"])
    has_target = _has_any(row, ["take_profit", "take_profit_price", "target", "target_price"])
    if has_stop and has_target:
        confirmations.append("predefined stop and target present")
        confirmation_sources.append("risk_plan")
    else:
        blockers.append("strategy: predefined stop and target required before entry")
    min_rr = _float(settings.get("PMO_MIN_RISK_REWARD_RATIO", 1.5), 1.5)
    if risk_reward >= min_rr:
        confirmations.append(f"risk/reward {risk_reward:g} meets minimum {min_rr:g}")
        confirmation_sources.append("risk_reward")
    elif risk_reward > 0:
        blockers.append(f"strategy: risk/reward {risk_reward:g} below minimum {min_rr:g}")

    if regime in {"BULL", "BULLISH"} and wants_long:
        confirmations.append("regime supports long setup")
        confirmation_sources.append("regime")
    elif regime in {"BEAR", "BEARISH"} and wants_short:
        confirmations.append("regime supports short setup")
        confirmation_sources.append("regime")
    elif regime in {"BEAR", "BEARISH", "NEUTRAL", "CHOPPY", "DEFENSIVE"} and wants_long:
        warnings.append(f"strategy: long setup conflicts with {regime} regime")

    sources = sorted(set(confirmation_sources))
    confluence_count = len(sources)
    if settings.get("PMO_STRATEGY_KNOWLEDGE_REQUIRE_CONFLUENCE", True) and confluence_count < required_confluence:
        blockers.append(f"strategy: {confluence_count}/{required_confluence} high-probability confluence checks")

    strategy_family = "UNCLASSIFIED"
    if "liquidity_shift" in sources:
        strategy_family = "REVERSAL_AT_KEY_LEVEL"
    elif "mean_reversion" in sources:
        strategy_family = "MEAN_REVERSION"
    elif "institutional_confluence" in sources:
        strategy_family = "FIB_OR_INSTITUTIONAL_CONFLUENCE"
    elif "market_structure" in sources and "technical_confluence" in sources:
        strategy_family = "TREND_FOLLOWING_PULLBACK"

    status = "BLOCK" if blockers else "WARN" if warnings else "PASS"
    return {
        "ok": True,
        "enabled": True,
        "version": PMO_STRATEGY_KNOWLEDGE_VERSION,
        "symbol": symbol,
        "status": status,
        "strategy_family": strategy_family,
        "confluence_count": confluence_count,
        "required_confluence": required_confluence,
        "confirmation_sources": sources,
        "confirmations": confirmations,
        "warnings": warnings,
        "blockers": blockers,
        "research_only": True,
        "score_boost_enabled": False,
        "live_unlocked": False,
        "orders_placed": False,
    }
