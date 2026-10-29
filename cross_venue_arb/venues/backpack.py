"""Backpack perps: hourly funding from markPrices, touch from the depth snapshot.

The public depth arrays are sorted ascending (worst bid first, best ask first).
Best bid is the highest bid and best ask is the lowest ask; we do not trust index 0.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from cross_venue_arb.config import AppConfig, venue_symbol
from cross_venue_arb.http import HttpStatusError, join_url, map_parallel, request_json
from cross_venue_arb.models import Quote, VenueResult, to_decimal, try_quote

_NAME = "backpack"


class BackpackVenue:
    name = _NAME

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        spec = config.venues[_NAME]
        self.base_url = spec.base_url
        self.kind = spec.kind
        self.quote_ccy = spec.quote_ccy
        self.interval = spec.funding_interval_hours

    def fetch(self, canonical_symbols: list[str], timeout: float) -> VenueResult:
        warnings: list[str] = []
        try:
            marks = request_json(
                "GET",
                join_url(self.base_url, "/api/v1/markPrices"),
                timeout=timeout,
            )
            mark_map = parse_mark_prices(marks)
        except (HttpStatusError, ValueError, KeyError, TypeError) as exc:
            return VenueResult(self.name, [], f"{type(exc).__name__}: {exc}")

        def load(symbol: str) -> tuple[str, dict[str, Any] | None, str | None]:
            venue_sym = venue_symbol(self.config, _NAME, symbol)
            try:
                payload = request_json(
                    "GET",
                    join_url(self.base_url, "/api/v1/depth", {"symbol": venue_sym}),
                    timeout=timeout,
                )
                return symbol, parse_depth_top(payload), None
            except (HttpStatusError, ValueError, KeyError, TypeError) as exc:
                return symbol, None, f"{type(exc).__name__}: {exc}"

        quotes: list[Quote] = []
        for symbol, top, err in map_parallel(load, canonical_symbols):
            venue_sym = venue_symbol(self.config, _NAME, symbol)
            if err:
                warnings.append(f"{symbol}: depth {err}")
            mark = mark_map.get(venue_sym)
            if top is None:
                if mark is None:
                    warnings.append(f"{symbol}: not on Backpack ({venue_sym})")
                else:
                    warnings.append(f"{symbol}: depth missing")
                continue
            quote = try_quote(
                venue=_NAME,
                canonical_symbol=symbol,
                venue_symbol=venue_sym,
                kind=self.kind,
                quote_ccy=self.quote_ccy,
                bid=top["bid"],
                ask=top["ask"],
                bid_size=top["bid_size"],
                ask_size=top["ask_size"],
                mark=None if mark is None else mark.get("mark"),
                index_price=None if mark is None else mark.get("index"),
                funding_rate=None if mark is None else mark.get("funding"),
                funding_interval_hours=self.interval,
                timestamp_ms=top["timestamp_ms"],
                price_source="depth",
            )
            if quote is None:
                warnings.append(f"{symbol}: invalid bid/ask")
                continue
            if mark is None:
                warnings.append(f"{symbol}: funding missing")
            quotes.append(quote)
        return VenueResult(self.name, quotes, None, warnings)


def parse_mark_prices(payload: Any) -> dict[str, dict[str, Decimal | None]]:
    if isinstance(payload, dict) and "message" in payload and "symbol" not in payload:
        raise ValueError(f"Backpack markPrices: {payload.get('message')}")
    if not isinstance(payload, list):
        raise ValueError("Backpack markPrices: unexpected payload")
    parsed: dict[str, dict[str, Decimal | None]] = {}
    for row in payload:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol")
        if not isinstance(symbol, str):
            continue
        parsed[symbol] = {
            "funding": to_decimal(row.get("fundingRate")),
            "mark": to_decimal(row.get("markPrice")),
            "index": to_decimal(row.get("indexPrice")),
        }
    return parsed


def parse_depth_top(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    bids = payload.get("bids")
    asks = payload.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
        return None
    bid_level = _best(bids, high=True)
    ask_level = _best(asks, high=False)
    if bid_level is None or ask_level is None:
        return None
    return {
        "bid": bid_level[0],
        "bid_size": bid_level[1],
        "ask": ask_level[0],
        "ask_size": ask_level[1],
        "timestamp_ms": _normalize_ms(payload.get("timestamp")),
    }


def _best(levels: list[Any], *, high: bool) -> tuple[Decimal, Decimal | None] | None:
    chosen: tuple[Decimal, Decimal | None] | None = None
    for level in levels:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        price = to_decimal(level[0])
        size = to_decimal(level[1])
        if price is None or price <= 0:
            continue
        if chosen is None:
            chosen = (price, size)
            continue
        if high and price > chosen[0]:
            chosen = (price, size)
        elif not high and price < chosen[0]:
            chosen = (price, size)
    return chosen


def _normalize_ms(value: Any) -> int | None:
    number = to_decimal(value)
    if number is None:
        return None
    whole = int(number)
    if whole > 10**14:
        return whole // 1000
    if whole < 10**11:
        return whole * 1000
    return whole
