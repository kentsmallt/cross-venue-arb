"""OKX USDT-margined perpetual swaps.

Ticker sizes are in contracts. Base size is contracts * ctVal * ctMult when
ctValCcy matches the canonical coin. Funding interval is taken from the gap
between fundingTime and nextFundingTime when both are present.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from cross_venue_arb.config import AppConfig, venue_symbol
from cross_venue_arb.http import HttpStatusError, join_url, request_json
from cross_venue_arb.models import Quote, VenueResult, to_decimal, try_quote

_NAME = "okx"


class OkxVenue:
    name = _NAME

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        spec = config.venues[_NAME]
        self.base_url = spec.base_url
        self.kind = spec.kind
        self.quote_ccy = spec.quote_ccy
        self.interval = spec.funding_interval_hours or Decimal("8")

    def fetch(self, canonical_symbols: list[str], timeout: float) -> VenueResult:
        try:
            tickers = request_json(
                "GET",
                join_url(self.base_url, "/api/v5/market/tickers", {"instType": "SWAP"}),
                timeout=timeout,
            )
            funding = request_json(
                "GET",
                join_url(self.base_url, "/api/v5/public/funding-rate", {"instId": "ANY"}),
                timeout=timeout,
            )
            instruments = request_json(
                "GET",
                join_url(self.base_url, "/api/v5/public/instruments", {"instType": "SWAP"}),
                timeout=timeout,
            )
            quotes, warnings = parse_okx(
                tickers,
                funding,
                instruments,
                canonical_symbols,
                self.config,
                self.kind,
                self.quote_ccy,
                self.interval,
            )
        except (HttpStatusError, ValueError, KeyError, TypeError) as exc:
            return VenueResult(self.name, [], f"{type(exc).__name__}: {exc}")
        return VenueResult(self.name, quotes, None, warnings)


def parse_okx(
    tickers: Any,
    funding: Any,
    instruments: Any,
    canonical_symbols: list[str],
    config: AppConfig,
    kind: str,
    quote_ccy: str,
    default_interval: Decimal,
) -> tuple[list[Quote], list[str]]:
    ticker_rows = _data(tickers, "tickers")
    funding_rows = _data(funding, "funding-rate")
    instrument_rows = _data(instruments, "instruments")
    by_inst = {_text(row.get("instId")): row for row in ticker_rows}
    fund_by_inst = {_text(row.get("instId")): row for row in funding_rows}
    spec_by_inst = {_text(row.get("instId")): row for row in instrument_rows}
    quotes: list[Quote] = []
    warnings: list[str] = []
    for canonical in canonical_symbols:
        inst = venue_symbol(config, _NAME, canonical)
        row = by_inst.get(inst)
        if row is None:
            warnings.append(f"{canonical}: no ticker ({inst})")
            continue
        fund = fund_by_inst.get(inst, {})
        spec = spec_by_inst.get(inst, {})
        bid_size, ask_size, size_note = _base_sizes(row, spec, canonical)
        if size_note:
            warnings.append(f"{canonical}: {size_note}")
        quote = try_quote(
            venue=_NAME,
            canonical_symbol=canonical,
            venue_symbol=inst,
            kind=kind,
            quote_ccy=quote_ccy,
            bid=to_decimal(row.get("bidPx")),
            ask=to_decimal(row.get("askPx")),
            bid_size=bid_size,
            ask_size=ask_size,
            funding_rate=to_decimal(fund.get("fundingRate")),
            funding_interval_hours=_interval_hours(fund, default_interval),
            timestamp_ms=_ms(row.get("ts")),
            price_source="ticker",
        )
        if quote is None:
            warnings.append(f"{canonical}: invalid bid/ask")
            continue
        quotes.append(quote)
    return quotes, warnings


def _base_sizes(
    ticker: dict[str, Any], spec: dict[str, Any], canonical: str
) -> tuple[Decimal | None, Decimal | None, str | None]:
    bid_contracts = to_decimal(ticker.get("bidSz"))
    ask_contracts = to_decimal(ticker.get("askSz"))
    ct_val = to_decimal(spec.get("ctVal"))
    ct_mult = to_decimal(spec.get("ctMult")) or Decimal("1")
    ct_ccy = spec.get("ctValCcy")
    if ct_val is None or not isinstance(ct_ccy, str):
        return None, None, "contract size unknown"
    if ct_ccy.upper() != canonical.upper():
        return None, None, f"ctValCcy {ct_ccy} does not match {canonical}"
    factor = ct_val * ct_mult

    def convert(contracts: Decimal | None) -> Decimal | None:
        if contracts is None:
            return None
        return contracts * factor

    return convert(bid_contracts), convert(ask_contracts), None


def _interval_hours(row: dict[str, Any], default: Decimal) -> Decimal:
    start = _ms(row.get("fundingTime"))
    end = _ms(row.get("nextFundingTime"))
    if start is None or end is None or end <= start:
        return default
    hours = Decimal(end - start) / Decimal("3600000")
    if hours <= 0:
        return default
    return hours


def _data(payload: Any, what: str) -> list[Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"OKX {what}: unexpected payload")
    if str(payload.get("code")) != "0":
        raise ValueError(f"OKX {what}: {payload.get('msg')}")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError(f"OKX {what}: missing data")
    return [row for row in data if isinstance(row, dict)]


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _ms(value: Any) -> int | None:
    if isinstance(value, str) and value.isdigit():
        return int(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    return None
