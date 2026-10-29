from decimal import Decimal

import pytest

from cross_venue_arb.config import default_config
from cross_venue_arb.models import try_quote
from cross_venue_arb.spreads import build_spreads, hourly_funding


def book(
    venue,
    bid,
    ask,
    *,
    symbol="BTC",
    kind="perp",
    ccy="USD",
    funding="0",
    interval="1",
    bid_size="2",
    ask_size="2",
):
    return try_quote(
        venue=venue,
        canonical_symbol=symbol,
        venue_symbol=symbol,
        kind=kind,
        quote_ccy=ccy,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=Decimal(bid_size),
        ask_size=Decimal(ask_size),
        funding_rate=None if funding is None else Decimal(funding),
        funding_interval_hours=None if interval is None else Decimal(interval),
        price_source="test",
    )


def test_gross_fees_and_flat_funding():
    cfg = default_config()
    cheap = book("hyperliquid", "99", "100", ccy="USD", funding="0.0001", interval="1")
    rich = book("backpack", "101", "102", ccy="USDC", funding="0.0001", interval="1")
    rows = build_spreads([cheap, rich], cfg)
    buy_cheap = next(row for row in rows if row.buy_venue == "hyperliquid")
    assert buy_cheap.gross_bps == Decimal("100")
    assert buy_cheap.fee_bps == Decimal("9.5")
    assert buy_cheap.funding_bps == Decimal("0")
    assert buy_cheap.buffer_bps == Decimal("2")
    assert buy_cheap.net_bps == Decimal("88.5")
    assert buy_cheap.opportunity is True
    assert buy_cheap.quote_fx is False
    assert buy_cheap.strategy == "perp_cross"


def test_eight_hour_funding_matches_hourly_rate():
    cfg = default_config()
    buy = book("hyperliquid", "99", "100", funding="0.0001", interval="1")
    sell = book("okx", "101", "102", ccy="USDT", funding="0.0008", interval="8")
    assert hourly_funding(buy) == Decimal("0.0001")
    assert hourly_funding(sell) == Decimal("0.0001")
    row = next(item for item in build_spreads([buy, sell], cfg) if item.buy_venue == "hyperliquid")
    assert row.funding_bps == Decimal("0")
    assert row.quote_fx is True
    assert row.buffer_bps == Decimal("3")


def test_short_funding_credit_and_maker_role():
    cfg = default_config()
    cfg.fee_role = "maker"
    buy = book("hyperliquid", "99", "100", funding="0", interval="1")
    sell = book("backpack", "101", "102", ccy="USDC", funding="0.0001", interval="1")
    row = next(item for item in build_spreads([buy, sell], cfg) if item.buy_venue == "hyperliquid")
    assert row.fee_bps == Decimal("3.5")
    assert row.funding_bps == Decimal("-1")
    assert row.net_bps == Decimal("100") - Decimal("3.5") - Decimal("-1") - Decimal("2")


def test_missing_perp_funding_is_not_an_opportunity():
    cfg = default_config()
    buy = book("hyperliquid", "99", "100", funding=None, interval=None)
    sell = book("backpack", "101", "102", ccy="USDC")
    row = next(item for item in build_spreads([buy, sell], cfg) if item.buy_venue == "hyperliquid")
    assert row.funding_known is False
    assert row.funding_bps == Decimal("0")
    assert row.opportunity is False
    assert "funding incomplete" in row.notes
    cfg.require_funding = False
    allowed = next(item for item in build_spreads([buy, sell], cfg) if item.buy_venue == "hyperliquid")
    assert allowed.opportunity is True


def test_spot_basis_has_zero_funding_and_a_note():
    cfg = default_config()
    spot = book(
        "binance_spot",
        "99",
        "100",
        kind="spot",
        ccy="USDT",
        funding=None,
        interval=None,
    )
    perp = book("hyperliquid", "101", "102", funding="0.0001", interval="1")
    row = next(item for item in build_spreads([spot, perp], cfg) if item.buy_venue == "binance_spot")
    assert row.strategy == "basis"
    assert row.funding_known is True
    assert row.funding_bps == Decimal("-1")
    assert "borrow" in row.notes


def test_divergent_mids_are_suspect_and_not_logged_as_opportunities():
    cfg = default_config()
    buy = book("hyperliquid", "99", "100")
    sell = book("backpack", "150", "151", ccy="USDC")
    row = next(item for item in build_spreads([buy, sell], cfg) if item.buy_venue == "hyperliquid")
    assert row.suspect is True
    assert row.opportunity is False
    assert row.gross_bps > cfg.min_net_bps


def test_thin_or_unknown_size_blocks_the_opportunity_flag():
    cfg = default_config()
    cfg.min_top_notional_usd = Decimal("1000")
    buy = book("hyperliquid", "99", "100", ask_size="0.01")
    sell = book("backpack", "101", "102", ccy="USDC", bid_size="0.01")
    row = next(item for item in build_spreads([buy, sell], cfg) if item.buy_venue == "hyperliquid")
    assert row.thin is True
    assert row.opportunity is False


def test_same_venue_and_other_symbols_are_not_crossed():
    cfg = default_config()
    btc = book("hyperliquid", "99", "100", symbol="BTC")
    eth = book("backpack", "9", "10", symbol="ETH", ccy="USDC")
    assert build_spreads([btc, eth], cfg) == []
    again = book("hyperliquid", "101", "102", symbol="BTC")
    assert build_spreads([btc, again], cfg) == []


def test_threshold_is_inclusive_and_negative_gross_is_not_an_opportunity():
    cfg = default_config()
    cfg.min_net_bps = Decimal("88.5")
    cheap = book("hyperliquid", "99", "100")
    rich = book("backpack", "101", "102", ccy="USDC")
    row = next(item for item in build_spreads([cheap, rich], cfg) if item.buy_venue == "hyperliquid")
    assert row.net_bps == Decimal("88.5")
    assert row.opportunity is True
    cfg.min_net_bps = Decimal("88.6")
    missed = next(item for item in build_spreads([cheap, rich], cfg) if item.buy_venue == "hyperliquid")
    assert missed.opportunity is False
    inverted = next(item for item in build_spreads([cheap, rich], cfg) if item.buy_venue == "backpack")
    assert inverted.gross_bps < 0
    assert inverted.opportunity is False


def test_crossed_book_is_dropped():
    assert book("hyperliquid", "101", "100") is None


def test_hourly_funding_rejects_bad_interval():
    quote = book("hyperliquid", "1", "1", funding="0.01", interval="0")
    assert quote is not None
    assert hourly_funding(quote) is None
