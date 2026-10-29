"""Cross-venue spread math.

Long the buy venue (lift the ask) and short the sell venue (hit the bid).
Positive funding means longs pay shorts, so the carry of this pair over the
configured horizon is:

    hourly(buy) - hourly(sell)

Spot funding is zero. Missing perp funding is treated as zero and flagged,
so it cannot silently become a credit.
"""

from __future__ import annotations

from decimal import Decimal

from cross_venue_arb.config import AppConfig
from cross_venue_arb.models import Quote, Spread

_BPS = Decimal("10000")


def stable_group(ccy: str) -> str:
    upper = ccy.upper()
    if upper in {"USD", "USDC"}:
        return "usd"
    if upper == "USDT":
        return "usdt"
    return upper


def hourly_funding(quote: Quote) -> Decimal | None:
    if quote.kind == "spot":
        return Decimal("0")
    if quote.funding_rate is None or quote.funding_interval_hours is None:
        return None
    if quote.funding_interval_hours <= 0:
        return None
    return quote.funding_rate / quote.funding_interval_hours


def build_spreads(quotes: list[Quote], config: AppConfig) -> list[Spread]:
    grouped: dict[str, list[Quote]] = {}
    for quote in quotes:
        grouped.setdefault(quote.canonical_symbol, []).append(quote)
    rows: list[Spread] = []
    for symbol, books in grouped.items():
        unique: dict[str, Quote] = {}
        for quote in books:
            unique[quote.venue] = quote
        ordered = list(unique.values())
        for buy in ordered:
            for sell in ordered:
                if buy.venue == sell.venue:
                    continue
                rows.append(_pair(symbol, buy, sell, config))
    rows.sort(key=lambda row: (-row.net_bps, row.canonical_symbol, row.buy_venue, row.sell_venue))
    return rows


def _pair(symbol: str, buy: Quote, sell: Quote, config: AppConfig) -> Spread:
    gross = (sell.bid - buy.ask) / buy.ask * _BPS
    fee = config.fee_bps(buy.venue) + config.fee_bps(sell.venue)
    funding_bps, funding_known = _funding_bps(buy, sell, config.funding_horizon_hours)
    quote_fx = stable_group(buy.quote_ccy) != stable_group(sell.quote_ccy)
    buffer = config.fee_buffer_bps + config.slippage_bps
    if quote_fx:
        buffer += config.stablecoin_buffer_bps
    net = gross - fee - funding_bps - buffer
    strategy = _strategy(buy.kind, sell.kind)
    thin = _thin(buy, sell, config.min_top_notional_usd)
    suspect = _suspect(buy, sell, config.max_mid_divergence_bps)
    funding_ok = funding_known or not config.require_funding
    opportunity = net >= config.min_net_bps and not thin and not suspect and funding_ok
    notes = _notes(strategy, quote_fx, funding_known, suspect, thin)
    return Spread(
        canonical_symbol=symbol,
        buy_venue=buy.venue,
        sell_venue=sell.venue,
        buy_kind=buy.kind,
        sell_kind=sell.kind,
        strategy=strategy,
        buy_ask=buy.ask,
        sell_bid=sell.bid,
        gross_bps=gross,
        fee_bps=fee,
        funding_bps=funding_bps,
        buffer_bps=buffer,
        net_bps=net,
        funding_known=funding_known,
        thin=thin,
        suspect=suspect,
        quote_fx=quote_fx,
        opportunity=opportunity,
        notes=notes,
    )


def _funding_bps(buy: Quote, sell: Quote, horizon_hours: Decimal) -> tuple[Decimal, bool]:
    buy_hourly = hourly_funding(buy)
    sell_hourly = hourly_funding(sell)
    known = buy_hourly is not None and sell_hourly is not None
    if buy_hourly is None:
        buy_hourly = Decimal("0")
    if sell_hourly is None:
        sell_hourly = Decimal("0")
    fraction = (buy_hourly - sell_hourly) * horizon_hours
    return fraction * _BPS, known


def _strategy(buy_kind: str, sell_kind: str) -> str:
    kinds = {buy_kind, sell_kind}
    if kinds == {"perp"}:
        return "perp_cross"
    if kinds == {"spot"}:
        return "spot_cross"
    return "basis"


def _thin(buy: Quote, sell: Quote, minimum: Decimal) -> bool:
    if minimum <= 0:
        return False
    buy_notional = _notional(buy.ask, buy.ask_size)
    sell_notional = _notional(sell.bid, sell.bid_size)
    if buy_notional is None or sell_notional is None:
        return True
    return buy_notional < minimum or sell_notional < minimum


def _notional(price: Decimal, size: Decimal | None) -> Decimal | None:
    if size is None or size <= 0:
        return None
    return price * size


def _suspect(buy: Quote, sell: Quote, cap_bps: Decimal) -> bool:
    if cap_bps <= 0:
        return False
    mid_buy = (buy.bid + buy.ask) / 2
    mid_sell = (sell.bid + sell.ask) / 2
    ref = min(mid_buy, mid_sell)
    if ref <= 0:
        return True
    divergence = abs(mid_buy - mid_sell) / ref * _BPS
    return divergence > cap_bps


def _notes(
    strategy: str,
    quote_fx: bool,
    funding_known: bool,
    suspect: bool,
    thin: bool,
) -> str:
    parts: list[str] = []
    if strategy == "basis":
        parts.append("spot leg ignores borrow")
    if quote_fx:
        parts.append("quote-currency buffer applied")
    if not funding_known:
        parts.append("funding incomplete; treated as 0")
    if suspect:
        parts.append("mid divergence above cap")
    if thin:
        parts.append("top size below min notional or unknown")
    return "; ".join(parts)
