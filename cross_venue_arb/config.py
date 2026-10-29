"""Defaults, TOML overrides, and CLI overrides. Trading stays off unless a boolean says otherwise."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError as exc:  # pragma: no cover - Python 3.11+ only
    raise RuntimeError("cross-venue-arb requires Python 3.11+") from exc

SYMBOL_RE = re.compile(r"^[A-Za-z0-9]{1,20}$")
VENUE_SYMBOL_RE = re.compile(r"^[A-Za-z0-9._:-]{1,40}$")
MIN_INTERVAL_SECONDS = 2.0

VENUE_NAMES = ("hyperliquid", "binance_um", "binance_spot", "backpack", "okx")

VENUE_ALIASES = {
    "hl": "hyperliquid",
    "hyperliquid": "hyperliquid",
    "binance": "binance_um",
    "binance_um": "binance_um",
    "binance-um": "binance_um",
    "binance_perp": "binance_um",
    "binance-perp": "binance_um",
    "binance_spot": "binance_spot",
    "binance-spot": "binance_spot",
    "bp": "backpack",
    "backpack": "backpack",
    "okx": "okx",
}

_TOP_LEVEL = {
    "mode",
    "live_trading_enabled",
    "symbols",
    "interval_seconds",
    "min_net_bps",
    "fee_buffer_bps",
    "slippage_bps",
    "stablecoin_buffer_bps",
    "funding_horizon_hours",
    "min_top_notional_usd",
    "max_mid_divergence_bps",
    "fee_role",
    "require_funding",
    "log_path",
    "output_format",
    "request_timeout_seconds",
    "once",
    "top",
    "venues",
    "symbol_map",
}
_VENUE_KEYS = {
    "enabled",
    "taker_fee_bps",
    "maker_fee_bps",
    "funding_interval_hours",
    "base_url",
}


class ConfigError(ValueError):
    pass


@dataclass
class VenueSpec:
    name: str
    enabled: bool
    kind: str
    quote_ccy: str
    taker_fee_bps: Decimal
    maker_fee_bps: Decimal
    funding_interval_hours: Decimal | None
    base_url: str


@dataclass
class AppConfig:
    mode: str = "paper"
    live_trading_enabled: bool = False
    symbols: list[str] = field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    interval_seconds: float = 10.0
    min_net_bps: Decimal = Decimal("0")
    fee_buffer_bps: Decimal = Decimal("1")
    slippage_bps: Decimal = Decimal("1")
    stablecoin_buffer_bps: Decimal = Decimal("1")
    funding_horizon_hours: Decimal = Decimal("1")
    min_top_notional_usd: Decimal = Decimal("0")
    max_mid_divergence_bps: Decimal = Decimal("500")
    fee_role: str = "taker"
    require_funding: bool = True
    log_path: str = "logs/opportunities.jsonl"
    output_format: str = "table"
    request_timeout_seconds: float = 12.0
    once: bool = False
    top: int = 0
    venues: dict[str, VenueSpec] = field(default_factory=dict)
    symbol_map: dict[str, dict[str, str]] = field(default_factory=dict)

    def fee_bps(self, venue: str) -> Decimal:
        spec = self.venues[venue]
        if self.fee_role == "maker":
            return spec.maker_fee_bps
        return spec.taker_fee_bps


def default_venues() -> dict[str, VenueSpec]:
    # Fee numbers are base-tier estimates, not a venue's current schedule.
    # Hyperliquid perps ~4.5/1.5 bps, Binance USD-M ~5/2, Binance spot ~10/10,
    # Backpack perps ~5/2, OKX swap ~5/2. Override in TOML after you check.
    rows = [
        VenueSpec(
            "hyperliquid",
            True,
            "perp",
            "USD",
            Decimal("4.5"),
            Decimal("1.5"),
            Decimal("1"),
            "https://api.hyperliquid.xyz",
        ),
        VenueSpec(
            "binance_um",
            True,
            "perp",
            "USDT",
            Decimal("5"),
            Decimal("2"),
            Decimal("8"),
            "https://fapi.binance.com",
        ),
        VenueSpec(
            "binance_spot",
            False,
            "spot",
            "USDT",
            Decimal("10"),
            Decimal("10"),
            None,
            "https://data-api.binance.vision",
        ),
        VenueSpec(
            "backpack",
            True,
            "perp",
            "USDC",
            Decimal("5"),
            Decimal("2"),
            Decimal("1"),
            "https://api.backpack.exchange",
        ),
        VenueSpec(
            "okx",
            True,
            "perp",
            "USDT",
            Decimal("5"),
            Decimal("2"),
            Decimal("8"),
            "https://www.okx.com",
        ),
    ]
    return {row.name: row for row in rows}


def default_config() -> AppConfig:
    return AppConfig(venues=default_venues())


def load_config(path: str | Path | None) -> AppConfig:
    cfg = default_config()
    if path is None:
        return cfg
    file_path = Path(path)
    if not file_path.is_file():
        raise ConfigError(f"config file not found: {file_path}")
    try:
        data = tomllib.loads(file_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML: {exc}") from None
    if not isinstance(data, dict):
        raise ConfigError("config root must be a table")
    _apply_table(cfg, data)
    return cfg


def apply_cli(
    cfg: AppConfig,
    *,
    symbols: str | None = None,
    interval: float | None = None,
    min_net_bps: str | None = None,
    fee_buffer_bps: str | None = None,
    slippage_bps: str | None = None,
    stablecoin_buffer_bps: str | None = None,
    funding_horizon_hours: str | None = None,
    min_top_notional_usd: str | None = None,
    fee_role: str | None = None,
    log_path: str | None = None,
    output_format: str | None = None,
    venues: str | None = None,
    mode: str | None = None,
    once: bool = False,
    top: int | None = None,
    require_funding: bool | None = None,
) -> AppConfig:
    if symbols:
        cfg.symbols = [_symbol(part) for part in symbols.split(",") if part.strip()]
        if not cfg.symbols:
            raise ConfigError("symbols list is empty")
    if interval is not None:
        cfg.interval_seconds = _positive_float(interval, "interval")
    if min_net_bps is not None:
        cfg.min_net_bps = _decimal(min_net_bps, "min_net_bps")
    if fee_buffer_bps is not None:
        cfg.fee_buffer_bps = _non_negative(fee_buffer_bps, "fee_buffer_bps")
    if slippage_bps is not None:
        cfg.slippage_bps = _non_negative(slippage_bps, "slippage_bps")
    if stablecoin_buffer_bps is not None:
        cfg.stablecoin_buffer_bps = _non_negative(
            stablecoin_buffer_bps, "stablecoin_buffer_bps"
        )
    if funding_horizon_hours is not None:
        cfg.funding_horizon_hours = _non_negative(
            funding_horizon_hours, "funding_horizon_hours"
        )
    if min_top_notional_usd is not None:
        cfg.min_top_notional_usd = _non_negative(
            min_top_notional_usd, "min_top_notional_usd"
        )
    if fee_role is not None:
        _set_fee_role(cfg, fee_role)
    if log_path is not None:
        cfg.log_path = log_path
    if output_format is not None:
        _set_format(cfg, output_format)
    if venues:
        _enable_only(cfg, venues)
    if mode is not None:
        _set_mode(cfg, mode)
    if once:
        cfg.once = True
    if top is not None:
        if top < 0:
            raise ConfigError("top must be >= 0")
        cfg.top = top
    if require_funding is not None:
        cfg.require_funding = require_funding
    return cfg


def effective_interval(cfg: AppConfig) -> float:
    return max(MIN_INTERVAL_SECONDS, cfg.interval_seconds)


def venue_symbol(cfg: AppConfig, venue: str, canonical: str) -> str:
    mapped = cfg.symbol_map.get(venue, {}).get(canonical)
    if mapped:
        return mapped
    if venue == "hyperliquid":
        return canonical
    if venue in {"binance_um", "binance_spot"}:
        return canonical + "USDT"
    if venue == "backpack":
        return f"{canonical}_USDC_PERP"
    if venue == "okx":
        return f"{canonical}-USDT-SWAP"
    raise ConfigError(f"unknown venue {venue}")


def resolve_venue_name(name: str) -> str:
    key = name.strip().lower()
    if key not in VENUE_ALIASES:
        known = ", ".join(VENUE_NAMES)
        raise ConfigError(f"unknown venue {name!r} (expected one of: {known})")
    return VENUE_ALIASES[key]


def _apply_table(cfg: AppConfig, data: dict[str, Any]) -> None:
    unknown = sorted(set(data) - _TOP_LEVEL)
    if unknown:
        raise ConfigError(f"unknown config keys: {', '.join(unknown)}")
    if "mode" in data:
        _set_mode(cfg, data["mode"])
    if "live_trading_enabled" in data:
        cfg.live_trading_enabled = _bool(data["live_trading_enabled"], "live_trading_enabled")
    if "symbols" in data:
        symbols = data["symbols"]
        if not isinstance(symbols, list) or not symbols:
            raise ConfigError("symbols must be a non-empty list")
        cfg.symbols = [_symbol(item) for item in symbols]
    if "interval_seconds" in data:
        cfg.interval_seconds = _positive_float(data["interval_seconds"], "interval_seconds")
    if "min_net_bps" in data:
        cfg.min_net_bps = _decimal(data["min_net_bps"], "min_net_bps")
    if "fee_buffer_bps" in data:
        cfg.fee_buffer_bps = _non_negative(data["fee_buffer_bps"], "fee_buffer_bps")
    if "slippage_bps" in data:
        cfg.slippage_bps = _non_negative(data["slippage_bps"], "slippage_bps")
    if "stablecoin_buffer_bps" in data:
        cfg.stablecoin_buffer_bps = _non_negative(
            data["stablecoin_buffer_bps"], "stablecoin_buffer_bps"
        )
    if "funding_horizon_hours" in data:
        cfg.funding_horizon_hours = _non_negative(
            data["funding_horizon_hours"], "funding_horizon_hours"
        )
    if "min_top_notional_usd" in data:
        cfg.min_top_notional_usd = _non_negative(
            data["min_top_notional_usd"], "min_top_notional_usd"
        )
    if "max_mid_divergence_bps" in data:
        cfg.max_mid_divergence_bps = _non_negative(
            data["max_mid_divergence_bps"], "max_mid_divergence_bps"
        )
    if "fee_role" in data:
        _set_fee_role(cfg, data["fee_role"])
    if "require_funding" in data:
        cfg.require_funding = _bool(data["require_funding"], "require_funding")
    if "log_path" in data:
        if not isinstance(data["log_path"], str):
            raise ConfigError("log_path must be a string")
        cfg.log_path = data["log_path"]
    if "output_format" in data:
        _set_format(cfg, data["output_format"])
    if "request_timeout_seconds" in data:
        cfg.request_timeout_seconds = _positive_float(
            data["request_timeout_seconds"], "request_timeout_seconds"
        )
    if "once" in data:
        cfg.once = _bool(data["once"], "once")
    if "top" in data:
        top = data["top"]
        if isinstance(top, bool) or not isinstance(top, int) or top < 0:
            raise ConfigError("top must be an integer >= 0")
        cfg.top = top
    if "symbol_map" in data:
        cfg.symbol_map = _symbol_map(data["symbol_map"])
    if "venues" in data:
        _apply_venues(cfg, data["venues"])


def _apply_venues(cfg: AppConfig, raw: Any) -> None:
    if not isinstance(raw, dict):
        raise ConfigError("venues must be a table")
    for name, body in raw.items():
        if name not in cfg.venues:
            raise ConfigError(f"unknown venue section {name!r}")
        if not isinstance(body, dict):
            raise ConfigError(f"venues.{name} must be a table")
        unknown = sorted(set(body) - _VENUE_KEYS)
        if unknown:
            raise ConfigError(f"unknown keys in venues.{name}: {', '.join(unknown)}")
        spec = cfg.venues[name]
        if "enabled" in body:
            spec.enabled = _bool(body["enabled"], f"venues.{name}.enabled")
        if "taker_fee_bps" in body:
            spec.taker_fee_bps = _non_negative(body["taker_fee_bps"], "taker_fee_bps")
        if "maker_fee_bps" in body:
            spec.maker_fee_bps = _non_negative(body["maker_fee_bps"], "maker_fee_bps")
        if "funding_interval_hours" in body:
            value = body["funding_interval_hours"]
            if value is None:
                spec.funding_interval_hours = None
            else:
                spec.funding_interval_hours = _non_negative(value, "funding_interval_hours")
        if "base_url" in body:
            url = body["base_url"]
            if not isinstance(url, str) or not url.startswith("https://"):
                raise ConfigError(f"venues.{name}.base_url must be an https URL")
            spec.base_url = url.rstrip("/")


def _symbol_map(raw: Any) -> dict[str, dict[str, str]]:
    if not isinstance(raw, dict):
        raise ConfigError("symbol_map must be a table")
    parsed: dict[str, dict[str, str]] = {}
    for venue, mapping in raw.items():
        canonical_venue = resolve_venue_name(str(venue))
        if not isinstance(mapping, dict):
            raise ConfigError(f"symbol_map.{venue} must be a table")
        parsed.setdefault(canonical_venue, {})
        for canonical, venue_sym in mapping.items():
            key = _symbol(canonical)
            if not isinstance(venue_sym, str) or not VENUE_SYMBOL_RE.fullmatch(venue_sym):
                raise ConfigError(f"invalid venue symbol for {key} on {canonical_venue}")
            parsed[canonical_venue][key] = venue_sym
    return parsed


def _enable_only(cfg: AppConfig, raw: str) -> None:
    selected = []
    for part in raw.split(","):
        if part.strip():
            selected.append(resolve_venue_name(part))
    if not selected:
        raise ConfigError("venues list is empty")
    chosen = set(selected)
    for name, spec in cfg.venues.items():
        spec.enabled = name in chosen


def _symbol(value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"invalid symbol {value!r}")
    text = value.strip().upper()
    if not SYMBOL_RE.fullmatch(text):
        raise ConfigError(f"invalid symbol {value!r}")
    return text


def _set_mode(cfg: AppConfig, value: Any) -> None:
    if not isinstance(value, str) or value not in {"paper", "live"}:
        raise ConfigError("mode must be 'paper' or 'live'")
    cfg.mode = value


def _set_fee_role(cfg: AppConfig, value: Any) -> None:
    if not isinstance(value, str) or value not in {"taker", "maker"}:
        raise ConfigError("fee_role must be 'taker' or 'maker'")
    cfg.fee_role = value


def _set_format(cfg: AppConfig, value: Any) -> None:
    if not isinstance(value, str) or value not in {"table", "json"}:
        raise ConfigError("output_format must be 'table' or 'json'")
    cfg.output_format = value


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{label} must be a boolean (fail closed)")
    return value


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ConfigError(f"{label} must be a number")
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise ConfigError(f"{label} must be a number") from exc
    if not number.is_finite():
        raise ConfigError(f"{label} must be finite")
    return number


def _non_negative(value: Any, label: str) -> Decimal:
    number = _decimal(value, label)
    if number < 0:
        raise ConfigError(f"{label} must be >= 0")
    return number


def _positive_float(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{label} must be a number")
    if value <= 0:
        raise ConfigError(f"{label} must be > 0")
    return float(value)
