"""Quotes and spread rows. Prices stay in Decimal end to end."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def to_decimal(value: Any) -> Decimal | None:
    if value is None or value is False or value is True:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return number


def decimal_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


@dataclass(frozen=True, slots=True)
class Quote:
    venue: str
    canonical_symbol: str
    venue_symbol: str
    kind: str
    quote_ccy: str
    bid: Decimal
    ask: Decimal
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    mark: Decimal | None = None
    index_price: Decimal | None = None
    funding_rate: Decimal | None = None
    funding_interval_hours: Decimal | None = None
    timestamp_ms: int | None = None
    price_source: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        for key, value in list(raw.items()):
            if isinstance(value, Decimal):
                raw[key] = decimal_str(value)
        return raw


def try_quote(
    *,
    venue: str,
    canonical_symbol: str,
    venue_symbol: str,
    kind: str,
    quote_ccy: str,
    bid: Decimal | None,
    ask: Decimal | None,
    bid_size: Decimal | None = None,
    ask_size: Decimal | None = None,
    mark: Decimal | None = None,
    index_price: Decimal | None = None,
    funding_rate: Decimal | None = None,
    funding_interval_hours: Decimal | None = None,
    timestamp_ms: int | None = None,
    price_source: str,
) -> Quote | None:
    if bid is None or ask is None:
        return None
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    if bid_size is not None and bid_size < 0:
        bid_size = None
    if ask_size is not None and ask_size < 0:
        ask_size = None
    return Quote(
        venue=venue,
        canonical_symbol=canonical_symbol,
        venue_symbol=venue_symbol,
        kind=kind,
        quote_ccy=quote_ccy,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        mark=mark,
        index_price=index_price,
        funding_rate=funding_rate,
        funding_interval_hours=funding_interval_hours,
        timestamp_ms=timestamp_ms,
        price_source=price_source,
    )


@dataclass(frozen=True, slots=True)
class Spread:
    canonical_symbol: str
    buy_venue: str
    sell_venue: str
    buy_kind: str
    sell_kind: str
    strategy: str
    buy_ask: Decimal
    sell_bid: Decimal
    gross_bps: Decimal
    fee_bps: Decimal
    funding_bps: Decimal
    buffer_bps: Decimal
    net_bps: Decimal
    funding_known: bool
    thin: bool
    suspect: bool
    quote_fx: bool
    opportunity: bool
    notes: str

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        for key, value in list(raw.items()):
            if isinstance(value, Decimal):
                raw[key] = decimal_str(value)
        return raw


@dataclass
class VenueResult:
    venue: str
    quotes: list[Quote]
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    timestamp: datetime
    requested_mode: str
    observe_only: bool
    orders_sent: int
    quotes: list[Quote]
    spreads: list[Spread]
    venue_errors: dict[str, str]
    venue_warnings: dict[str, list[str]]

    @property
    def opportunities(self) -> list[Spread]:
        return [row for row in self.spreads if row.opportunity]
