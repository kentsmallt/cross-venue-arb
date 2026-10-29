"""Binance public books.

USD-M perps use fapi.binance.com and can return HTTP 451 from some regions.
Spot uses the public market-data host data-api.binance.vision and is off
by default so basis trades are opt-in.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from cross_venue_arb.config import AppConfig, venue_symbol
from cross_venue_arb.http import HttpStatusError, join_url, request_json
from cross_venue_arb.models import Quote, VenueResult, to_decimal, try_quote


class BinanceUmVenue:
    name = "binance_um"

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        spec = config.venues[self.name]
        self.base_url = spec.base_url
        self.kind = spec.kind
        self.quote_ccy = spec.quote_ccy
        self.interval = spec.funding_interval_hours

    def fetch(self, canonical_symbols: list[str], timeout: float) -> VenueResult:
        try:
            books = request_json(
                "GET",
                join_url(self.base_url, "/fapi/v1/ticker/bookTicker"),
                timeout=timeout,
            )
            premium = request_json(
                "GET",
                join_url(self.base_url, "/fapi/v1/premiumIndex"),
                timeout=timeout,
            )
            quotes, warnings = parse_binance_perp(
                books,
                premium,
                canonical_symbols,
                self.config,
                self.kind,
                self.quote_ccy,
                self.interval,
            )
        except (HttpStatusError, ValueError, KeyError, TypeError) as exc:
            return VenueResult(self.name, [], f"{type(exc).__name__}: {exc}")
        return VenueResult(self.name, quotes, None, warnings)


class BinanceSpotVenue:
    name = "binance_spot"

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        spec = config.venues[self.name]
        self.base_url = spec.base_url
        self.kind = spec.kind
        self.quote_ccy = spec.quote_ccy

    def fetch(self, canonical_symbols: list[str], timeout: float) -> VenueResult:
        try:
            books = request_json(
                "GET",
                join_url(self.base_url, "/api/v3/ticker/bookTicker"),
                timeout=timeout,
            )
            quotes, warnings = parse_binance_spot(
                books,
                canonical_symbols,
                self.config,
                self.kind,
                self.quote_ccy,
            )
        except (HttpStatusError, ValueError, KeyError, TypeError) as exc:
            return VenueResult(self.name, [], f"{type(exc).__name__}: {exc}")
        return VenueResult(self.name, quotes, None, warnings)


def parse_binance_perp(
    books: Any,
    premium: Any,
    canonical_symbols: list[str],
    config: AppConfig,
    kind: str,
    quote_ccy: str,
    interval: Decimal | None,
) -> tuple[list[Quote], list[str]]:
    book_rows = _rows(books, "bookTicker")
    premium_rows = _rows(premium, "premiumIndex")
    by_symbol = {_text(row.get("symbol")): row for row in book_rows if isinstance(row, dict)}
    funding = {_text(row.get("symbol")): row for row in premium_rows if isinstance(row, dict)}
    quotes: list[Quote] = []
    warnings: list[str] = []
    for canonical in canonical_symbols:
        venue_sym = venue_symbol(config, "binance_um", canonical)
        row = by_symbol.get(venue_sym)
        if row is None:
            warnings.append(f"{canonical}: no book ({venue_sym})")
            continue
        fund = funding.get(venue_sym, {})
        quote = try_quote(
            venue="binance_um",
            canonical_symbol=canonical,
            venue_symbol=venue_sym,
            kind=kind,
            quote_ccy=quote_ccy,
            bid=to_decimal(row.get("bidPrice")),
            ask=to_decimal(row.get("askPrice")),
            bid_size=to_decimal(row.get("bidQty")),
            ask_size=to_decimal(row.get("askQty")),
            mark=to_decimal(fund.get("markPrice")),
            index_price=to_decimal(fund.get("indexPrice")),
            funding_rate=to_decimal(fund.get("lastFundingRate")),
            funding_interval_hours=interval,
            timestamp_ms=_ms(fund.get("time")),
            price_source="bookTicker",
        )
        if quote is None:
            warnings.append(f"{canonical}: invalid bid/ask")
            continue
        quotes.append(quote)
    return quotes, warnings


def parse_binance_spot(
    books: Any,
    canonical_symbols: list[str],
    config: AppConfig,
    kind: str,
    quote_ccy: str,
) -> tuple[list[Quote], list[str]]:
    rows = _rows(books, "bookTicker")
    by_symbol = {_text(row.get("symbol")): row for row in rows if isinstance(row, dict)}
    quotes: list[Quote] = []
    warnings: list[str] = []
    for canonical in canonical_symbols:
        venue_sym = venue_symbol(config, "binance_spot", canonical)
        row = by_symbol.get(venue_sym)
        if row is None:
            warnings.append(f"{canonical}: no book ({venue_sym})")
            continue
        quote = try_quote(
            venue="binance_spot",
            canonical_symbol=canonical,
            venue_symbol=venue_sym,
            kind=kind,
            quote_ccy=quote_ccy,
            bid=to_decimal(row.get("bidPrice")),
            ask=to_decimal(row.get("askPrice")),
            bid_size=to_decimal(row.get("bidQty")),
            ask_size=to_decimal(row.get("askQty")),
            price_source="bookTicker",
        )
        if quote is None:
            warnings.append(f"{canonical}: invalid bid/ask")
            continue
        quotes.append(quote)
    return quotes, warnings


def _rows(payload: Any, what: str) -> list[Any]:
    if isinstance(payload, dict):
        if "msg" in payload and "symbol" not in payload:
            raise ValueError(f"Binance {what}: {payload.get('msg')}")
        return [payload]
    if not isinstance(payload, list):
        raise ValueError(f"Binance {what}: unexpected payload")
    return payload


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _ms(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
