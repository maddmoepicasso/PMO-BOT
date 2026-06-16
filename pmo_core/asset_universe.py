"""Universal asset-class registry for PMO BOT.

This module is intentionally conservative. It lets PMO recognize, classify,
report, and explain markets before any execution adapter is allowed to submit
orders. Unknown broker/data support is treated as scan-only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Dict, Iterable, List, Optional


@dataclass(frozen=True)
class AssetClassSpec:
    asset_class: str
    display_name: str
    category: str
    examples: List[str]
    symbol_format: str
    tradeable_directly: bool
    scan_supported: bool
    paper_supported: bool
    live_supported: bool
    default_mode: str
    risk_tier: str
    default_max_notional: float
    default_max_daily_trades: int
    requires_margin: bool
    requires_options_approval: bool
    requires_futures_approval: bool
    requires_crypto_approval: bool
    requires_short_locate: bool
    requires_special_data_feed: bool
    supports_fractional: bool
    supports_shorting: bool
    supports_options: bool
    supports_extended_hours: bool
    supports_24_7: bool
    normal_market_hours: str
    broker_adapter_required: str
    data_adapter_required: str
    allowed_order_types: List[str]
    blocked_order_types: List[str]
    required_exit_plan: bool
    proof_requirements: Dict[str, Any]
    dashboard_badge: str
    safety_notes: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UniversalOrderRequest:
    symbol: str
    normalized_symbol: str = ""
    asset_class: str = "UNKNOWN"
    broker: str = "alpaca"
    side: str = ""
    action: str = ""
    quantity: Optional[float] = None
    notional: Optional[float] = None
    order_type: str = "market"
    time_in_force: str = "day"
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    trailing_stop: Optional[float] = None
    option_type: str = ""
    strike: Optional[float] = None
    expiration: str = ""
    contract_multiplier: Optional[float] = None
    futures_contract_month: str = ""
    currency_pair: str = ""
    crypto_pair: str = ""
    strategy_tag: str = ""
    signal_score: Optional[float] = None
    risk_reward: Optional[float] = None
    max_loss_usd: Optional[float] = None
    proof_required: bool = True
    paper_only: bool = True
    live_allowed: bool = False
    blocked_reason: str = ""


DEFAULT_PROOF_REQUIREMENTS: Dict[str, Dict[str, Any]] = {
    "STOCK": {"min_paper_trades": 30, "min_closed_trades": 30, "min_win_rate": 0.52, "min_profit_factor": 1.25, "max_failed_executions": 0, "proof_days": 30},
    "ETF": {"min_paper_trades": 30, "min_closed_trades": 30, "min_win_rate": 0.52, "min_profit_factor": 1.20, "max_failed_executions": 0, "proof_days": 30},
    "LEVERAGED_ETF": {"min_paper_trades": 60, "min_closed_trades": 60, "min_win_rate": 0.58, "min_profit_factor": 1.45, "max_failed_executions": 0, "proof_days": 45, "live_default_blocked": True},
    "INVERSE_ETF": {"min_paper_trades": 60, "min_closed_trades": 60, "min_win_rate": 0.58, "min_profit_factor": 1.45, "max_failed_executions": 0, "proof_days": 45, "live_default_blocked": True},
    "CRYPTO_SPOT": {"min_paper_trades": 50, "min_closed_trades": 50, "min_win_rate": 0.55, "min_profit_factor": 1.35, "max_failed_executions": 0, "proof_days": 45},
    "STOCK_OPTION": {"min_paper_trades": 75, "min_closed_trades": 75, "min_win_rate": 0.56, "min_profit_factor": 1.50, "max_failed_executions": 0, "proof_days": 60},
    "ETF_OPTION": {"min_paper_trades": 75, "min_closed_trades": 75, "min_win_rate": 0.56, "min_profit_factor": 1.50, "max_failed_executions": 0, "proof_days": 60},
    "INDEX_OPTION": {"min_paper_trades": 100, "min_closed_trades": 100, "min_win_rate": 0.58, "min_profit_factor": 1.60, "max_failed_executions": 0, "proof_days": 90, "live_default_blocked": True},
    "FUTURE": {"min_paper_trades": 100, "min_closed_trades": 100, "min_win_rate": 0.58, "min_profit_factor": 1.60, "max_failed_executions": 0, "proof_days": 90, "live_default_blocked": True},
    "FOREX_SPOT": {"min_paper_trades": 100, "min_closed_trades": 100, "min_win_rate": 0.58, "min_profit_factor": 1.50, "max_failed_executions": 0, "proof_days": 90, "live_default_blocked": True},
}


LEVERAGED_ETF_SYMBOLS = {
    "TQQQ", "SQQQ", "SOXL", "SOXS", "SPXL", "SPXS", "UPRO", "SPXU", "TNA", "TZA",
    "LABU", "LABD", "FAS", "FAZ", "TECL", "TECS", "FNGU", "FNGD", "NUGT", "DUST",
    "BOIL", "KOLD", "UVXY", "SVIX", "VXX",
}
INVERSE_ETF_SYMBOLS = {"SQQQ", "SOXS", "SPXS", "SPXU", "TZA", "LABD", "FAZ", "TECS", "FNGD", "DUST", "KOLD", "SH", "PSQ", "DOG", "RWM"}
COMMON_ETFS = {
    "SPY", "QQQ", "DIA", "IWM", "RSP", "VTI", "VOO", "XLK", "XLF", "XLE", "XLV", "XLY",
    "XLP", "XLI", "XLC", "XLU", "XLB", "XLRE", "SMH", "XBI", "KRE", "XHB", "XRT", "IBB",
    "EFA", "GDX", "GLD", "SLV", "TLT", "IEF", "SHY", "HYG", "LQD", "ARKK",
}
INDEX_SYMBOLS = {"SPX", "SPXW", "XSP", "RUT", "NDX", "VIX", "DJX"}
CRYPTO_BASES = {"BTC", "ETH", "SOL", "AVAX", "LINK", "DOGE", "LTC", "BCH", "ADA", "XRP", "MATIC", "DOT"}
FOREX_BASES = {"EUR", "GBP", "USD", "JPY", "CAD", "AUD", "CHF", "NZD", "MXN", "CNH"}
FUTURE_ROOTS = {"ES", "MES", "NQ", "MNQ", "YM", "RTY", "CL", "GC", "SI", "HG", "ZB", "ZN", "ZF", "ZT", "6E", "6J", "6B", "6A", "BTC", "ETH", "ZC", "ZS", "ZW"}


def _proof(asset_class: str) -> Dict[str, Any]:
    if asset_class in DEFAULT_PROOF_REQUIREMENTS:
        return dict(DEFAULT_PROOF_REQUIREMENTS[asset_class])
    if asset_class.endswith("_FUTURE") or asset_class == "FUTURES_OPTION":
        return dict(DEFAULT_PROOF_REQUIREMENTS["FUTURE"])
    return {"min_paper_trades": 30, "min_closed_trades": 30, "min_win_rate": 0.52, "min_profit_factor": 1.25, "max_failed_executions": 0, "proof_days": 30}


def _spec(
    asset_class: str,
    display_name: str,
    category: str,
    examples: Iterable[str],
    symbol_format: str,
    default_mode: str = "SCAN_ONLY",
    risk_tier: str = "MEDIUM",
    tradeable_directly: bool = True,
    scan_supported: bool = True,
    paper_supported: bool = False,
    live_supported: bool = False,
    default_max_notional: float = 100.0,
    default_max_daily_trades: int = 5,
    requires_margin: bool = False,
    requires_options_approval: bool = False,
    requires_futures_approval: bool = False,
    requires_crypto_approval: bool = False,
    requires_short_locate: bool = False,
    requires_special_data_feed: bool = False,
    supports_fractional: bool = False,
    supports_shorting: bool = False,
    supports_options: bool = False,
    supports_extended_hours: bool = False,
    supports_24_7: bool = False,
    normal_market_hours: str = "REGULAR_MARKET",
    broker_adapter_required: str = "UNKNOWN",
    data_adapter_required: str = "UNKNOWN",
    allowed_order_types: Optional[List[str]] = None,
    blocked_order_types: Optional[List[str]] = None,
    required_exit_plan: bool = True,
    dashboard_badge: str = "SCAN",
    safety_notes: str = "Scan-only until broker, data, account permission, proof, and owner approval pass.",
) -> AssetClassSpec:
    return AssetClassSpec(
        asset_class=asset_class,
        display_name=display_name,
        category=category,
        examples=list(examples),
        symbol_format=symbol_format,
        tradeable_directly=tradeable_directly,
        scan_supported=scan_supported,
        paper_supported=paper_supported,
        live_supported=live_supported,
        default_mode=default_mode,
        risk_tier=risk_tier,
        default_max_notional=default_max_notional,
        default_max_daily_trades=default_max_daily_trades,
        requires_margin=requires_margin,
        requires_options_approval=requires_options_approval,
        requires_futures_approval=requires_futures_approval,
        requires_crypto_approval=requires_crypto_approval,
        requires_short_locate=requires_short_locate,
        requires_special_data_feed=requires_special_data_feed,
        supports_fractional=supports_fractional,
        supports_shorting=supports_shorting,
        supports_options=supports_options,
        supports_extended_hours=supports_extended_hours,
        supports_24_7=supports_24_7,
        normal_market_hours=normal_market_hours,
        broker_adapter_required=broker_adapter_required,
        data_adapter_required=data_adapter_required,
        allowed_order_types=allowed_order_types or ["market", "limit", "stop", "stop_limit"],
        blocked_order_types=blocked_order_types or [],
        required_exit_plan=required_exit_plan,
        proof_requirements=_proof(asset_class),
        dashboard_badge=dashboard_badge,
        safety_notes=safety_notes,
    )


def _build_registry() -> Dict[str, AssetClassSpec]:
    rows = [
        _spec("STOCK", "Common Stock", "Equity", ["AAPL", "MSFT", "NVDA"], "UPPERCASE_TICKER", "PAPER_READY", "MEDIUM", paper_supported=True, supports_fractional=True, supports_shorting=True, supports_extended_hours=True, broker_adapter_required="alpaca", data_adapter_required="alpaca_stock"),
        _spec("ETF", "Exchange-Traded Fund", "ETF/ETP", ["SPY", "QQQ", "VTI"], "UPPERCASE_TICKER", "PAPER_READY", "MEDIUM", paper_supported=True, supports_fractional=True, supports_shorting=True, supports_options=True, supports_extended_hours=True, broker_adapter_required="alpaca", data_adapter_required="alpaca_stock"),
        _spec("ETP", "Exchange-Traded Product", "ETF/ETP", ["GLD", "SLV", "USO"], "UPPERCASE_TICKER", risk_tier="MEDIUM_HIGH"),
        _spec("ETN", "Exchange-Traded Note", "ETF/ETP", ["VXX", "AMJ"], "UPPERCASE_TICKER", risk_tier="HIGH", dashboard_badge="HIGH_RISK"),
        _spec("LEVERAGED_ETF", "Leveraged ETF", "ETF/ETP", ["TQQQ", "SOXL", "UPRO"], "UPPERCASE_TICKER", "PAPER_ONLY", "HIGH", paper_supported=True, broker_adapter_required="alpaca", data_adapter_required="alpaca_stock", dashboard_badge="LIVE_LOCKED", safety_notes="Complex product; paper-only until separate proof requirements pass."),
        _spec("INVERSE_ETF", "Inverse ETF", "ETF/ETP", ["SQQQ", "SH", "PSQ"], "UPPERCASE_TICKER", "PAPER_ONLY", "HIGH", paper_supported=True, broker_adapter_required="alpaca", data_adapter_required="alpaca_stock", dashboard_badge="LIVE_LOCKED"),
        _spec("SINGLE_STOCK_ETF", "Single-Stock ETF", "ETF/ETP", ["TSLL", "NVDL"], "UPPERCASE_TICKER", risk_tier="VERY_HIGH", dashboard_badge="SCAN_ONLY"),
        _spec("REIT", "REIT", "Equity", ["O", "PLD", "VNQ"], "UPPERCASE_TICKER", "SCAN_ONLY", "MEDIUM", paper_supported=False, broker_adapter_required="alpaca", data_adapter_required="alpaca_stock"),
        _spec("BDC", "Business Development Company", "Equity", ["ARCC", "MAIN"], "UPPERCASE_TICKER", "CONDITIONAL", "MEDIUM", broker_adapter_required="alpaca", data_adapter_required="alpaca_stock", dashboard_badge="CONDITIONAL", safety_notes="Conditional scan-first; add dividend/liquidity/exposure checks before paper testing."),
        _spec("ADR", "American Depositary Receipt", "Equity", ["BABA", "TM"], "UPPERCASE_TICKER", "CONDITIONAL", "MEDIUM_HIGH", broker_adapter_required="alpaca", data_adapter_required="alpaca_stock", dashboard_badge="CONDITIONAL", safety_notes="Conditional scan-first; add ADR fee, country-risk, liquidity, and data checks before paper testing."),
        _spec("OTC_STOCK", "OTC Stock", "Equity", ["TCEHY", "NSRGY"], "OTC_TICKER", risk_tier="HIGH", requires_special_data_feed=True, dashboard_badge="SCAN_ONLY"),
        _spec("PREFERRED_STOCK", "Preferred Stock", "Equity", ["BAC.PR.L"], "PREFERRED_TICKER", risk_tier="MEDIUM_HIGH"),
        _spec("WARRANT", "Warrant", "Equity Derivative", ["XYZ.WS"], "WARRANT_TICKER", risk_tier="HIGH"),
        _spec("RIGHT", "Right", "Equity Derivative", ["XYZ.RT"], "RIGHT_TICKER", risk_tier="HIGH"),
        _spec("CLOSED_END_FUND", "Closed-End Fund", "Fund", ["PTY", "PDI"], "UPPERCASE_TICKER", "CONDITIONAL", "MEDIUM_HIGH", broker_adapter_required="alpaca", data_adapter_required="alpaca_stock", dashboard_badge="CONDITIONAL", safety_notes="Conditional scan-first; add premium/discount, leverage, distribution, and liquidity checks before paper testing."),
        _spec("MUTUAL_FUND", "Mutual Fund", "Fund", ["VTSAX", "FXAIX"], "FUND_TICKER", "SCAN_ONLY", "LOW_MEDIUM", tradeable_directly=False, required_exit_plan=False, dashboard_badge="SCAN_ONLY", safety_notes="Redeems at NAV; not an intraday PMO execution target."),
        _spec("MONEY_MARKET_FUND", "Money Market Fund", "Fund", ["VMFXX", "SPAXX"], "FUND_TICKER", "SCAN_ONLY", "LOW", tradeable_directly=False, required_exit_plan=False),
        _spec("TREASURY", "U.S. Treasury", "Fixed Income", ["91282CJK8", "T-BILL"], "CUSIP_OR_TREASURY_CODE", "SCAN_ONLY", "LOW", tradeable_directly=False, default_max_daily_trades=0, required_exit_plan=False, data_adapter_required="fixed_income"),
        _spec("CORPORATE_BOND", "Corporate Bond", "Fixed Income", ["IBM 2034", "CUSIP"], "CUSIP", "SCAN_ONLY", "MEDIUM", tradeable_directly=False, requires_special_data_feed=True, required_exit_plan=False),
        _spec("MUNICIPAL_BOND", "Municipal Bond", "Fixed Income", ["NY MUNI", "CUSIP"], "CUSIP", "SCAN_ONLY", "MEDIUM", tradeable_directly=False, requires_special_data_feed=True, required_exit_plan=False),
        _spec("AGENCY_BOND", "Agency Bond", "Fixed Income", ["FNMA", "FHLB"], "CUSIP", "SCAN_ONLY", "LOW_MEDIUM", tradeable_directly=False, required_exit_plan=False),
        _spec("CD", "Certificate of Deposit", "Fixed Income", ["BROKERED_CD"], "CUSIP", "SCAN_ONLY", "LOW", tradeable_directly=False, required_exit_plan=False),
        _spec("STOCK_OPTION", "Stock Option", "Option", ["AAPL 2026-01-16 200C"], "OCC_OPTION", "PAPER_READY", "HIGH", paper_supported=True, requires_options_approval=True, supports_options=True, broker_adapter_required="alpaca_options", data_adapter_required="alpaca_options", allowed_order_types=["market", "limit"], blocked_order_types=["sell_to_open_uncovered"]),
        _spec("ETF_OPTION", "ETF Option", "Option", ["SPY 2026-01-16 500C"], "OCC_OPTION", "PAPER_READY", "HIGH", paper_supported=True, requires_options_approval=True, supports_options=True, broker_adapter_required="alpaca_options", data_adapter_required="alpaca_options", allowed_order_types=["market", "limit"], blocked_order_types=["sell_to_open_uncovered"]),
        _spec("INDEX_OPTION", "Index Option", "Option", ["SPXW", "RUT"], "INDEX_OPTION", "SCAN_ONLY", "VERY_HIGH", requires_options_approval=True, requires_special_data_feed=True, supports_options=True, broker_adapter_required="index_options_broker"),
        _spec("VOLATILITY_OPTION", "Volatility Option", "Option", ["VIX"], "VOL_OPTION", "SCAN_ONLY", "VERY_HIGH", requires_options_approval=True, requires_special_data_feed=True, supports_options=True),
        _spec("FUTURES_OPTION", "Futures Option", "Futures Option", ["ES option"], "FOP", "SCAN_ONLY", "VERY_HIGH", requires_futures_approval=True, requires_options_approval=True, requires_margin=True, broker_adapter_required="futures_broker"),
        _spec("EQUITY_INDEX_FUTURE", "Equity Index Future", "Future", ["/ES", "/MES", "/NQ"], "SLASH_ROOT_CONTRACT", "SCAN_ONLY", "VERY_HIGH", requires_futures_approval=True, requires_margin=True, broker_adapter_required="futures_broker", data_adapter_required="futures_data"),
        _spec("TREASURY_FUTURE", "Treasury Future", "Future", ["/ZN", "/ZB"], "SLASH_ROOT_CONTRACT", "SCAN_ONLY", "VERY_HIGH", requires_futures_approval=True, requires_margin=True),
        _spec("INTEREST_RATE_FUTURE", "Interest Rate Future", "Future", ["SOFR", "/SR3"], "SLASH_ROOT_CONTRACT", "SCAN_ONLY", "VERY_HIGH", requires_futures_approval=True, requires_margin=True),
        _spec("FX_FUTURE", "FX Future", "Future", ["/6E", "/6J"], "SLASH_ROOT_CONTRACT", "SCAN_ONLY", "VERY_HIGH", requires_futures_approval=True, requires_margin=True),
        _spec("ENERGY_FUTURE", "Energy Future", "Future", ["/CL", "/NG"], "SLASH_ROOT_CONTRACT", "SCAN_ONLY", "VERY_HIGH", requires_futures_approval=True, requires_margin=True),
        _spec("METAL_FUTURE", "Metal Future", "Future", ["/GC", "/SI", "/HG"], "SLASH_ROOT_CONTRACT", "SCAN_ONLY", "VERY_HIGH", requires_futures_approval=True, requires_margin=True),
        _spec("AGRICULTURE_FUTURE", "Agriculture Future", "Future", ["/ZC", "/ZS", "/ZW"], "SLASH_ROOT_CONTRACT", "SCAN_ONLY", "VERY_HIGH", requires_futures_approval=True, requires_margin=True),
        _spec("CRYPTO_FUTURE", "Crypto Future", "Future", ["/BTC", "/ETH"], "SLASH_ROOT_CONTRACT", "SCAN_ONLY", "VERY_HIGH", requires_futures_approval=True, requires_crypto_approval=True, requires_margin=True, supports_24_7=True),
        _spec("FOREX_SPOT", "Spot Forex", "Forex", ["EUR/USD", "USD/JPY"], "CCY/CCY", "SCAN_ONLY", "VERY_HIGH", requires_margin=True, broker_adapter_required="forex_broker", data_adapter_required="forex_data", supports_24_7=False, normal_market_hours="24/5"),
        _spec("CRYPTO_SPOT", "Crypto Spot", "Crypto", ["BTC/USD", "ETH/USD"], "BASE/USD", "PAPER_READY", "HIGH", paper_supported=True, requires_crypto_approval=True, supports_fractional=True, supports_24_7=True, normal_market_hours="24/7", broker_adapter_required="alpaca_crypto", data_adapter_required="alpaca_crypto", allowed_order_types=["market", "limit"]),
        _spec("CRYPTO_OPTION", "Crypto Option", "Crypto Derivative", ["BTC option"], "EXCHANGE_SPECIFIC", "SCAN_ONLY", "VERY_HIGH", requires_crypto_approval=True, requires_options_approval=True, supports_24_7=True),
        _spec("CRYPTO_PERPETUAL", "Crypto Perpetual", "Crypto Derivative", ["BTC-PERP"], "EXCHANGE_SPECIFIC", "SCAN_ONLY", "EXTREME", requires_crypto_approval=True, requires_margin=True, supports_24_7=True),
        _spec("COMMODITY_ETF", "Commodity ETF", "ETF/ETP", ["GLD", "SLV", "USO"], "UPPERCASE_TICKER", "CONDITIONAL", "HIGH", broker_adapter_required="alpaca", data_adapter_required="alpaca_stock", dashboard_badge="CONDITIONAL", safety_notes="Conditional scan-first; add commodity structure, roll-risk, liquidity, and data checks before paper testing."),
        _spec("CURRENCY_ETF", "Currency ETF", "ETF/ETP", ["UUP", "FXE"], "UPPERCASE_TICKER", "CONDITIONAL", "HIGH", broker_adapter_required="alpaca", data_adapter_required="alpaca_stock", dashboard_badge="CONDITIONAL", safety_notes="Conditional scan-first; add currency exposure, macro-risk, liquidity, and data checks before paper testing."),
        _spec("VOLATILITY_ETP", "Volatility ETP", "ETF/ETP", ["VXX", "UVXY"], "UPPERCASE_TICKER", "SCAN_ONLY", "EXTREME", dashboard_badge="HIGH_RISK"),
        _spec("TOKENIZED_STOCK", "Tokenized Stock", "Digital Asset", ["tokenized AAPL"], "PROVIDER_SPECIFIC", "SCAN_ONLY", "EXTREME", requires_special_data_feed=True, supports_24_7=True),
        _spec("TOKENIZED_TREASURY", "Tokenized Treasury", "Digital Asset", ["tokenized T-bill"], "PROVIDER_SPECIFIC", "SCAN_ONLY", "HIGH", requires_special_data_feed=True, supports_24_7=True),
        _spec("TOKENIZED_FUND", "Tokenized Fund", "Digital Asset", ["tokenized fund"], "PROVIDER_SPECIFIC", "SCAN_ONLY", "HIGH", requires_special_data_feed=True, supports_24_7=True),
        _spec("EVENT_CONTRACT", "Event Contract", "Event Market", ["CPI event"], "PROVIDER_SPECIFIC", "SCAN_ONLY", "EXTREME", requires_special_data_feed=True),
        _spec("PREDICTION_MARKET", "Prediction Market", "Event Market", ["election market"], "PROVIDER_SPECIFIC", "SCAN_ONLY", "EXTREME", requires_special_data_feed=True),
        _spec("REAL_ESTATE_PUBLIC", "Public Real Estate", "Real Estate", ["REIT", "VNQ"], "UPPERCASE_TICKER", "SCAN_ONLY", "MEDIUM"),
        _spec("PRIVATE_MARKET_SCAN_ONLY", "Private Market", "Alternative", ["private credit", "private equity"], "PROVIDER_SPECIFIC", "SCAN_ONLY", "EXTREME", tradeable_directly=False),
        _spec("UNKNOWN", "Unknown Asset", "Unknown", ["UNKNOWN"], "UNKNOWN", "SCAN_ONLY", "UNKNOWN", tradeable_directly=False, scan_supported=True, paper_supported=False, live_supported=False, default_max_notional=0, default_max_daily_trades=0, required_exit_plan=False, dashboard_badge="UNKNOWN", safety_notes="Unknown assets are scan-only and blocked from execution."),
    ]
    return {row.asset_class: row for row in rows}


ASSET_CLASS_REGISTRY: Dict[str, AssetClassSpec] = _build_registry()


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip().upper() for v in value if str(v).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                import ast
                parsed = ast.literal_eval(text)
                return _as_list(parsed)
            except Exception:
                pass
        return [part.strip().upper() for part in text.split(",") if part.strip()]
    return [str(value).strip().upper()]


def normalize_symbol(symbol: str, asset_class: Optional[str] = None) -> str:
    s = str(symbol or "").strip().upper().replace(" ", "")
    if not s:
        return ""
    cls = (asset_class or "").upper()
    if cls == "CRYPTO_SPOT" and "/" not in s and "-" in s:
        s = s.replace("-", "/")
    if cls == "FOREX_SPOT" and "/" not in s and len(s) == 6:
        s = f"{s[:3]}/{s[3:]}"
    if cls.endswith("_FUTURE") and not s.startswith("/") and re.match(r"^[A-Z0-9]{1,3}$", s):
        s = "/" + s
    return s


def get_asset_class(symbol: str, hint: Optional[str] = None) -> str:
    if hint and str(hint).upper() in ASSET_CLASS_REGISTRY:
        return str(hint).upper()
    s = normalize_symbol(symbol)
    if not s:
        return "UNKNOWN"
    if s in LEVERAGED_ETF_SYMBOLS:
        return "INVERSE_ETF" if s in INVERSE_ETF_SYMBOLS else "LEVERAGED_ETF"
    if s in COMMON_ETFS:
        if s in {"GLD", "SLV", "USO"}:
            return "COMMODITY_ETF"
        return "ETF"
    if s in INDEX_SYMBOLS:
        return "INDEX_OPTION" if s.endswith("W") or s in {"SPX", "RUT", "NDX", "VIX"} else "UNKNOWN"
    if "/" in s:
        left, right = s.split("/", 1)
        if left in CRYPTO_BASES and right in {"USD", "USDT", "USDC"}:
            return "CRYPTO_SPOT"
        if left in FOREX_BASES and right in FOREX_BASES:
            return "FOREX_SPOT"
    if s.startswith("/"):
        root = re.sub(r"[^A-Z0-9]", "", s[1:])
        if root in {"ES", "MES", "NQ", "MNQ", "YM", "RTY"}:
            return "EQUITY_INDEX_FUTURE"
        if root in {"ZB", "ZN", "ZF", "ZT"}:
            return "TREASURY_FUTURE"
        if root in {"6E", "6J", "6B", "6A"}:
            return "FX_FUTURE"
        if root in {"CL", "NG", "RB"}:
            return "ENERGY_FUTURE"
        if root in {"GC", "SI", "HG"}:
            return "METAL_FUTURE"
        if root in {"ZC", "ZS", "ZW"}:
            return "AGRICULTURE_FUTURE"
        if root in {"BTC", "ETH"}:
            return "CRYPTO_FUTURE"
        if root in FUTURE_ROOTS:
            return "EQUITY_INDEX_FUTURE"
    if re.match(r"^[A-Z]{1,5}(\.[A-Z])?$", s):
        return "STOCK"
    if re.match(r"^[A-Z]{4,5}X$", s):
        return "MUTUAL_FUND"
    if re.match(r"^[0-9A-Z]{9}$", s):
        return "TREASURY"
    return "UNKNOWN"


def get_asset_spec(asset_class: str) -> AssetClassSpec:
    return ASSET_CLASS_REGISTRY.get(str(asset_class or "").upper(), ASSET_CLASS_REGISTRY["UNKNOWN"])


def list_supported_asset_classes() -> List[str]:
    return sorted(ASSET_CLASS_REGISTRY)


def list_scan_only_asset_classes() -> List[str]:
    return [k for k, v in ASSET_CLASS_REGISTRY.items() if v.default_mode == "SCAN_ONLY" or not v.paper_supported]


def list_paper_enabled_asset_classes(settings: Dict[str, Any]) -> List[str]:
    return [c for c in _as_list(settings.get("PMO_PAPER_ENABLED_ASSET_CLASSES")) if c in ASSET_CLASS_REGISTRY]


def list_live_eligible_asset_classes(settings: Dict[str, Any]) -> List[str]:
    if settings.get("PMO_BLOCK_LIVE_FOR_NEW_ASSET_CLASSES", True):
        return [c for c in _as_list(settings.get("PMO_LIVE_ENABLED_ASSET_CLASSES")) if c in ASSET_CLASS_REGISTRY]
    return [c for c in _as_list(settings.get("PMO_LIVE_ENABLED_ASSET_CLASSES")) if c in ASSET_CLASS_REGISTRY]


def _capability_for_broker(broker_name: str) -> Dict[str, Any]:
    broker = str(broker_name or "alpaca").lower()
    if broker == "alpaca":
        from pmo_core.brokers.alpaca_capabilities import CAPABILITIES
    elif broker == "futures":
        from pmo_core.brokers.futures_capabilities import CAPABILITIES
    elif broker == "forex":
        from pmo_core.brokers.forex_capabilities import CAPABILITIES
    elif broker in {"crypto_exchange", "crypto"}:
        from pmo_core.brokers.crypto_exchange_capabilities import CAPABILITIES
    elif broker in {"fixed_income", "bond"}:
        from pmo_core.brokers.fixed_income_capabilities import CAPABILITIES
    else:
        return {"broker": broker, "supported_asset_classes": [], "paper_supported": False, "live_supported": False}
    return CAPABILITIES


def broker_supports_asset(asset_class: str, broker_name: str, account_config: Optional[Dict[str, Any]] = None) -> bool:
    cap = _capability_for_broker(broker_name)
    cls = str(asset_class or "").upper()
    return cls in set(cap.get("supported_asset_classes", []))


def data_feed_supports_asset(asset_class: str, data_provider: str) -> bool:
    cls = str(asset_class or "").upper()
    provider = str(data_provider or "").lower()
    if provider == "alpaca":
        return cls in {
            "STOCK", "ETF", "ETP", "ETN", "LEVERAGED_ETF", "INVERSE_ETF",
            "SINGLE_STOCK_ETF", "REIT", "BDC", "ADR", "COMMODITY_ETF",
            "CURRENCY_ETF", "VOLATILITY_ETP", "CRYPTO_SPOT",
            "STOCK_OPTION", "ETF_OPTION",
        }
    if provider == "alpaca_stock":
        return cls in {"STOCK", "ETF", "ETP", "ETN", "LEVERAGED_ETF", "INVERSE_ETF", "SINGLE_STOCK_ETF", "REIT", "BDC", "ADR", "COMMODITY_ETF", "CURRENCY_ETF", "VOLATILITY_ETP"}
    if provider in {"alpaca_crypto", "crypto"}:
        return cls == "CRYPTO_SPOT"
    if provider in {"alpaca_options", "options"}:
        return cls in {"STOCK_OPTION", "ETF_OPTION"}
    return False


def validate_asset_for_execution(symbol: str, asset_class: str, settings: Dict[str, Any], account: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    account = account or {}
    cls = get_asset_class(symbol, asset_class)
    spec = get_asset_spec(cls)
    normalized = normalize_symbol(symbol, cls)
    blockers: List[Dict[str, str]] = []
    supported = set(_as_list(settings.get("PMO_SUPPORTED_ASSET_CLASSES")))
    scan_only = set(_as_list(settings.get("PMO_SCAN_ONLY_ASSET_CLASSES")))
    paper_enabled = set(list_paper_enabled_asset_classes(settings))
    live_enabled = set(list_live_eligible_asset_classes(settings))
    broker = str(settings.get("PMO_ASSET_DEFAULT_BROKER", "alpaca"))
    data_provider = str(settings.get("PMO_ASSET_DEFAULT_DATA_PROVIDER", "alpaca"))

    def block(code: str, reason: str) -> None:
        blockers.append({"code": code, "reason": reason})

    if cls == "UNKNOWN":
        block("UNKNOWN_ASSET_CLASS", "Asset class could not be identified.")
    if supported and cls not in supported:
        block("ASSET_NOT_SUPPORTED_BY_PMO_SETTINGS", f"{cls} is not in PMO_SUPPORTED_ASSET_CLASSES.")
    if cls in scan_only or spec.default_mode == "SCAN_ONLY":
        block("SCAN_ONLY_ASSET_CLASS", f"{cls} is configured scan-only.")
    if settings.get("PMO_REQUIRE_BROKER_CAPABILITY_CHECK", True) and not broker_supports_asset(cls, broker, account):
        block("BROKER_UNSUPPORTED", f"{broker} capability map does not support {cls}.")
    if settings.get("PMO_REQUIRE_DATA_FEED_CHECK", True) and not data_feed_supports_asset(cls, data_provider):
        block("DATA_FEED_UNSUPPORTED", f"{data_provider} data feed does not support {cls}.")
    if cls not in paper_enabled:
        block("PAPER_NOT_ENABLED", f"{cls} is not enabled for paper execution.")
    if spec.requires_options_approval and not account.get("options_approved", settings.get("OPTIONS_ORDER_ENABLED", False)):
        block("NEEDS_OPTIONS_APPROVAL", "Account/options switch is not approved for this asset class.")
    if spec.requires_futures_approval and not account.get("futures_approved", False):
        block("NEEDS_FUTURES_APPROVAL", "Futures approval and broker adapter are required.")
    if spec.requires_crypto_approval and cls != "CRYPTO_SPOT" and not account.get("crypto_approved", False):
        block("NEEDS_CRYPTO_APPROVAL", "Crypto derivative approval is required.")
    if settings.get("PMO_REQUIRE_EXIT_PLAN_BY_ASSET_CLASS", True) and spec.required_exit_plan and not settings.get("PMO_REQUIRE_PROTECTIVE_EXIT_PLAN", True):
        block("EXIT_PLAN_REQUIRED", "PMO protective exit plan must remain enabled.")
    live_locked = not (bool(settings.get("PMO_ALLOW_LIVE_TRADING")) and bool(settings.get("PMO_LIVE_TRADING_ENABLED")) and cls in live_enabled)

    status = "PAPER_READY" if not blockers else "BLOCKED"
    if cls in scan_only or spec.default_mode == "SCAN_ONLY":
        status = "SCAN_ONLY"
    if blockers and any(b["code"] == "BROKER_UNSUPPORTED" for b in blockers):
        status = "UNSUPPORTED"
    return {
        "ok": not blockers,
        "symbol": symbol,
        "normalized_symbol": normalized,
        "asset_class": cls,
        "status": status,
        "paper_enabled": cls in paper_enabled and not any(b["code"] in {"SCAN_ONLY_ASSET_CLASS", "BROKER_UNSUPPORTED"} for b in blockers),
        "live_locked": live_locked,
        "broker": broker,
        "data_provider": data_provider,
        "blockers": blockers,
        "next_action": blockers[0]["reason"] if blockers else "Paper execution can be considered after normal PMO order gates pass.",
    }


def explain_why_asset_blocked(symbol: str, asset_class: Optional[str], settings: Dict[str, Any], account: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return validate_asset_for_execution(symbol, asset_class or get_asset_class(symbol), settings, account)


def validate_universal_order(order: UniversalOrderRequest, settings: Dict[str, Any], account: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cls = order.asset_class or get_asset_class(order.symbol)
    result = validate_asset_for_execution(order.symbol, cls, settings, account)
    spec = get_asset_spec(result["asset_class"])
    if order.order_type and order.order_type not in spec.allowed_order_types:
        result["blockers"].append({"code": "ORDER_TYPE_BLOCKED", "reason": f"{order.order_type} is not allowed for {spec.asset_class}."})
    if order.notional and order.notional > spec.default_max_notional:
        result["blockers"].append({"code": "ASSET_NOTIONAL_LIMIT", "reason": f"Notional exceeds {spec.asset_class} default asset limit."})
    if order.live_allowed and result.get("live_locked", True):
        result["blockers"].append({"code": "LIVE_LOCKED", "reason": "Live trading is locked for this asset class."})
    result["ok"] = not result["blockers"]
    result["status"] = result["status"] if result["ok"] else "BLOCKED"
    return result


def build_asset_dashboard_rows(settings: Dict[str, Any], account: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    account = account or {}
    supported = set(_as_list(settings.get("PMO_SUPPORTED_ASSET_CLASSES")))
    scan_only = set(_as_list(settings.get("PMO_SCAN_ONLY_ASSET_CLASSES")))
    paper_enabled = set(list_paper_enabled_asset_classes(settings))
    live_enabled = set(list_live_eligible_asset_classes(settings))
    broker = str(settings.get("PMO_ASSET_DEFAULT_BROKER", "alpaca"))
    data_provider = str(settings.get("PMO_ASSET_DEFAULT_DATA_PROVIDER", "alpaca"))
    rows: List[Dict[str, Any]] = []
    for cls, spec in ASSET_CLASS_REGISTRY.items():
        if cls == "UNKNOWN":
            continue
        broker_ok = broker_supports_asset(cls, broker, account)
        data_ok = data_feed_supports_asset(cls, data_provider)
        in_supported = not supported or cls in supported
        is_conditional = spec.default_mode == "CONDITIONAL"
        is_scan_only = cls in scan_only or spec.default_mode == "SCAN_ONLY" or is_conditional
        paper_ok = cls in paper_enabled and broker_ok and data_ok and not is_scan_only
        live_locked = cls not in live_enabled or bool(settings.get("PMO_BLOCK_LIVE_FOR_NEW_ASSET_CLASSES", True))
        if not in_supported:
            status = "UNSUPPORTED"
        elif is_conditional:
            status = "CONDITIONAL"
        elif is_scan_only:
            status = "SCAN"
        elif not broker_ok:
            status = "UNSUPPORTED"
        elif not data_ok:
            status = "NEEDS DATA FEED"
        elif paper_ok:
            status = "PAPER"
        else:
            status = "NEEDS APPROVAL"
        if not live_locked and paper_ok:
            status = "LIVE LOCK REVIEW"
        rows.append({
            "asset_class": cls,
            "display_name": spec.display_name,
            "category": spec.category,
            "examples": ", ".join(spec.examples[:3]),
            "scan_status": "ON" if spec.scan_supported and in_supported else "OFF",
            "data_provider": data_provider if data_ok else "NEEDS DATA FEED",
            "broker_support": "YES" if broker_ok else "NO",
            "paper_enabled": paper_ok,
            "live_locked": live_locked,
            "proof_score": 0,
            "risk_tier": spec.risk_tier,
            "status": status,
            "dashboard_badge": spec.dashboard_badge,
            "next_action": _next_action(status, spec),
            "safety_notes": spec.safety_notes,
            "proof_requirements": spec.proof_requirements,
        })
    return rows


def _next_action(status: str, spec: AssetClassSpec) -> str:
    return {
        "SCAN": "Keep scan-only until broker/data/proof plan is added.",
        "CONDITIONAL": "Recognized and scan-first; add asset-specific checks before paper enablement.",
        "PAPER": "Paper-test only; collect asset-class proof before live review.",
        "UNSUPPORTED": "Add broker/data adapter or keep scan-only.",
        "NEEDS DATA FEED": "Add/enable data feed for this asset class.",
        "NEEDS APPROVAL": "Confirm account permissions and PMO settings.",
        "LIVE LOCK REVIEW": "Owner/admin review required before any live unlock.",
    }.get(status, spec.safety_notes)


def build_asset_universe_snapshot(settings: Dict[str, Any], account: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    rows = build_asset_dashboard_rows(settings, account)
    counts: Dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    high_risk = [r for r in rows if r["risk_tier"] in {"HIGH", "VERY_HIGH", "EXTREME"}]
    return {
        "ok": True,
        "enabled": bool(settings.get("PMO_UNIVERSAL_ASSET_REGISTRY_ENABLED", True)),
        "mode": settings.get("PMO_ASSET_UNIVERSE_MODE", "SCAN_FIRST"),
        "counts": counts,
        "total_asset_classes": len(rows),
        "paper_ready": [r["asset_class"] for r in rows if r["status"] == "PAPER"],
        "scan_only": [r["asset_class"] for r in rows if r["status"] in {"SCAN", "CONDITIONAL"}],
        "unsupported": [r["asset_class"] for r in rows if r["status"] == "UNSUPPORTED"],
        "needs_data": [r["asset_class"] for r in rows if r["status"] == "NEEDS DATA FEED"],
        "high_risk": [r["asset_class"] for r in high_risk],
        "rows": rows,
        "safety_note": "Universal asset registry is scan/classify/report first. It does not unlock live trading.",
    }


def build_market_capability_matrix(settings: Dict[str, Any], account: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    account = account or {}
    brokers = ["alpaca", "futures", "forex", "crypto_exchange", "fixed_income"]
    rows = []
    for cls in sorted(k for k in ASSET_CLASS_REGISTRY if k != "UNKNOWN"):
        row = {"asset_class": cls}
        for broker in brokers:
            supported = broker_supports_asset(cls, broker, account)
            row[broker] = "SCAN" if not supported else ("PAPER" if cls in list_paper_enabled_asset_classes(settings) else "LIVE LOCKED")
        rows.append(row)
    return {"ok": True, "brokers": brokers, "rows": rows}
