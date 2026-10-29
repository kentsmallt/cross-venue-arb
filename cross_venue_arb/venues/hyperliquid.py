"""Hyperliquid perps: meta (funding, mark, impact) plus L2 top of book."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from cross_venue_arb.config import AppConfig, venue_symbol
from cross_venue_arb.http import HttpStatusError, join_url, map_parallel, request_json
from cross_venue_arb.models import Quote, VenueResult, to_decimal, try_quote

_NAME = "hyperliquid"


class HyperliquidVenue:
    name = _NAME

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        spec = config.venues[_NAME]
        self.info_url = join_url(spec.base_url, "/info")
        self.kind = spec.kind
        self.quote_ccy = spec.quote_ccy
        self.interval = spec.funding_interval_hours

    def fetch(self, canonical_symbols: list[str], timeout: float) -> VenueResult:
        warnings: list[str] = []
        try:
            meta_payload = request_json(
                "POST",
                self.info_url,
                {"type": "metaAndAssetCtxs"},
                timeout,
            )
            contexts = parse_asset_contexts(meta_payload)
        except (HttpStatusError, ValueError, KeyError, TypeError) as exc:
            return VenueResult(self.name, [], f"{type(exc).__name__}: {exc}")

        def load(symbol: str) -> tuple[str, dict[str, Any] | None, str | None]:
            coin = venue_symbol(self.config, _NAME, symbol)
            try:
                payload = request_json(
                    "POST",
                    self.info_url,
                    {"type": "l2Book", "coin": coin},
                    timeout,
                )
                return symbol, parse_l2_top(payload), None
            except (HttpStatusError, ValueError, KeyError, TypeError) as exc:
                return symbol, None, f"{type(exc).__name__}: {exc}"

        quotes: list[Quote] = []
        for symbol, top, err in map_parallel(load, canonical_symbols):
            coin = venue_symbol(self.config, _NAME, symbol)
            ctx = contexts.get(coin)
            if err:
                warnings.append(f"{symbol}: l2 {err}")
            if ctx is None and top is None:
                warnings.append(f"{symbol}: not on Hyperliquid")
                continue
            quote = quote_from_parts(
                canonical_symbol=symbol,
                coin=coin,
                top=top,
                ctx=ctx,
                kind=self.kind,
                quote_ccy=self.quote_ccy,
                interval=self.interval,
            )
            if quote is None:
                warnings.append(f"{symbol}: invalid bid/ask")
                continue
            quotes.append(quote)
        return VenueResult(self.name, quotes, None, warnings)


def parse_asset_contexts(payload: Any) -> dict[str, dict[str, Decimal | None]]:
    if not isinstance(payload, list) or len(payload) < 2:
        raise ValueError("unexpected metaAndAssetCtxs payload")
    meta, contexts = payload[0], payload[1]
    universe = meta.get("universe") if isinstance(meta, dict) else None
    if not isinstance(universe, list) or not isinstance(contexts, list):
        raise ValueError("unexpected metaAndAssetCtxs payload")
    parsed: dict[str, dict[str, Decimal | None]] = {}
    for asset, ctx in zip(universe, contexts):
        if not isinstance(asset, dict) or not isinstance(ctx, dict):
            continue
        name = asset.get("name")
        if not isinstance(name, str):
            continue
        impact = ctx.get("impactPxs") if isinstance(ctx.get("impactPxs"), list) else []
        parsed[name] = {
            "funding": to_decimal(ctx.get("funding")),
            "mark": to_decimal(ctx.get("markPx")),
            "oracle": to_decimal(ctx.get("oraclePx")),
            "impact_bid": to_decimal(impact[0]) if len(impact) > 0 else None,
            "impact_ask": to_decimal(impact[1]) if len(impact) > 1 else None,
        }
    return parsed


def parse_l2_top(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    levels = payload.get("levels")
    if not isinstance(levels, list) or len(levels) < 2:
        return None
    bids, asks = levels[0], levels[1]
    if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
        return None
    bid = max(bids, key=lambda level: _level_px(level, missing=Decimal("-1")))
    ask = min(asks, key=lambda level: _level_px(level, missing=Decimal("Inf")))
    if not isinstance(bid, dict) or not isinstance(ask, dict):
        return None
    bid_px = to_decimal(bid.get("px"))
    ask_px = to_decimal(ask.get("px"))
    if bid_px is None or ask_px is None:
        return None
    timestamp = payload.get("time")
    timestamp_ms = int(timestamp) if isinstance(timestamp, (int, float)) else None
    return {
        "bid": bid_px,
        "ask": ask_px,
        "bid_size": to_decimal(bid.get("sz")),
        "ask_size": to_decimal(ask.get("sz")),
        "timestamp_ms": timestamp_ms,
    }


def _level_px(level: Any, missing: Decimal) -> Decimal:
    if not isinstance(level, dict):
        return missing
    return to_decimal(level.get("px")) or missing


def quote_from_parts(
    *,
    canonical_symbol: str,
    coin: str,
    top: dict[str, Any] | None,
    ctx: dict[str, Decimal | None] | None,
    kind: str,
    quote_ccy: str,
    interval: Decimal | None,
) -> Quote | None:
    if top is not None:
        bid = top["bid"]
        ask = top["ask"]
        bid_size = top["bid_size"]
        ask_size = top["ask_size"]
        timestamp_ms = top["timestamp_ms"]
        source = "l2"
    elif ctx is not None and ctx.get("impact_bid") is not None and ctx.get("impact_ask") is not None:
        bid = ctx["impact_bid"]
        ask = ctx["impact_ask"]
        bid_size = None
        ask_size = None
        timestamp_ms = None
        source = "impact"
    else:
        return None
    return try_quote(
        venue=_NAME,
        canonical_symbol=canonical_symbol,
        venue_symbol=coin,
        kind=kind,
        quote_ccy=quote_ccy,
        bid=bid,
        ask=ask,
        bid_size=bid_size,
        ask_size=ask_size,
        mark=None if ctx is None else ctx.get("mark"),
        index_price=None if ctx is None else ctx.get("oracle"),
        funding_rate=None if ctx is None else ctx.get("funding"),
        funding_interval_hours=interval,
        timestamp_ms=timestamp_ms,
        price_source=source,
    )
