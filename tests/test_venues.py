from decimal import Decimal

import pytest

from cross_venue_arb.config import default_config
from cross_venue_arb.venues.backpack import parse_depth_top, parse_mark_prices
from cross_venue_arb.venues.binance import parse_binance_perp, parse_binance_spot
from cross_venue_arb.venues.hyperliquid import parse_asset_contexts, parse_l2_top, quote_from_parts
from cross_venue_arb.venues.okx import parse_okx


def test_hyperliquid_prefers_l2_and_keeps_funding():
    payload = [
        {"universe": [{"name": "BTC"}, {"name": "ETH"}]},
        [
            {
                "funding": "0.0001",
                "markPx": "100",
                "oraclePx": "100.5",
                "impactPxs": ["90", "91"],
            },
            {"funding": "0.0002", "markPx": "10", "oraclePx": "10", "impactPxs": ["9", "11"]},
        ],
    ]
    ctx = parse_asset_contexts(payload)
    top = parse_l2_top(
        {
            "time": 1_700_000_000_000,
            "levels": [
                [{"px": "99", "sz": "1.5"}, {"px": "98", "sz": "3"}],
                [{"px": "101", "sz": "2"}, {"px": "102", "sz": "1"}],
            ],
        }
    )
    quote = quote_from_parts(
        canonical_symbol="BTC",
        coin="BTC",
        top=top,
        ctx=ctx["BTC"],
        kind="perp",
        quote_ccy="USD",
        interval=Decimal("1"),
    )
    assert quote is not None
    assert quote.bid == Decimal("99")
    assert quote.ask == Decimal("101")
    assert quote.bid_size == Decimal("1.5")
    assert quote.price_source == "l2"
    assert quote.funding_rate == Decimal("0.0001")
    assert quote.mark == Decimal("100")


def test_hyperliquid_impact_fallback_when_book_missing():
    ctx = parse_asset_contexts(
        [
            {"universe": [{"name": "BTC"}]},
            [{"funding": "0.0000125", "markPx": "100", "oraclePx": "100", "impactPxs": ["99.5", "100.5"]}],
        ]
    )
    quote = quote_from_parts(
        canonical_symbol="BTC",
        coin="BTC",
        top=None,
        ctx=ctx["BTC"],
        kind="perp",
        quote_ccy="USD",
        interval=Decimal("1"),
    )
    assert quote is not None
    assert quote.bid == Decimal("99.5")
    assert quote.ask == Decimal("100.5")
    assert quote.price_source == "impact"
    assert quote.bid_size is None


def test_backpack_depth_is_not_the_first_bid():
    top = parse_depth_top(
        {
            "bids": [["20000", "0.01"], ["79950", "1.2"], ["79960.5", "0.4"]],
            "asks": [["79961.0", "0.8"], ["159000", "0.01"]],
            "timestamp": 1_793_277_430_323_028,
        }
    )
    assert top is not None
    assert top["bid"] == Decimal("79960.5")
    assert top["bid_size"] == Decimal("0.4")
    assert top["ask"] == Decimal("79961.0")
    assert top["ask_size"] == Decimal("0.8")
    assert top["timestamp_ms"] == 1_793_277_430_323
    marks = parse_mark_prices(
        [
            {
                "symbol": "BTC_USDC_PERP",
                "fundingRate": "0.0000125",
                "markPrice": "79962.5",
                "indexPrice": "79970",
            }
        ]
    )
    assert marks["BTC_USDC_PERP"]["funding"] == Decimal("0.0000125")


def test_binance_merges_funding_and_rejects_error_body():
    cfg = default_config()
    books = [
        {
            "symbol": "BTCUSDT",
            "bidPrice": "100",
            "askPrice": "101",
            "bidQty": "3",
            "askQty": "4",
        }
    ]
    premium = [
        {
            "symbol": "BTCUSDT",
            "lastFundingRate": "0.0001",
            "markPrice": "100.5",
            "indexPrice": "100.4",
            "time": 1_700_000_000_000,
        }
    ]
    quotes, warnings = parse_binance_perp(
        books,
        premium,
        ["BTC", "ETH"],
        cfg,
        "perp",
        "USDT",
        Decimal("8"),
    )
    assert warnings == ["ETH: no book (ETHUSDT)"]
    assert quotes[0].bid == Decimal("100")
    assert quotes[0].funding_rate == Decimal("0.0001")
    assert quotes[0].funding_interval_hours == Decimal("8")
    with pytest.raises(ValueError, match="restricted"):
        parse_binance_perp(
            {"code": 0, "msg": "Service unavailable from a restricted location"},
            [],
            ["BTC"],
            cfg,
            "perp",
            "USDT",
            Decimal("8"),
        )
    spot, _ = parse_binance_spot(books[0], ["BTC"], cfg, "spot", "USDT")
    assert spot[0].kind == "spot"
    assert spot[0].funding_rate is None


def test_okx_converts_contracts_and_funding_interval():
    cfg = default_config()
    start = 1_793_289_600_000
    end = start + 8 * 3_600_000
    quotes, warnings = parse_okx(
        {"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "bidPx": "100", "askPx": "101", "bidSz": "100", "askSz": "50", "ts": "1700000000000"}]},
        {"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "fundingRate": "0.0008", "fundingTime": str(start), "nextFundingTime": str(end)}]},
        {"code": "0", "data": [{"instId": "BTC-USDT-SWAP", "ctVal": "0.01", "ctMult": "1", "ctValCcy": "BTC"}]},
        ["BTC"],
        cfg,
        "perp",
        "USDT",
        Decimal("8"),
    )
    assert warnings == []
    assert quotes[0].bid_size == Decimal("1")
    assert quotes[0].ask_size == Decimal("0.5")
    assert quotes[0].funding_interval_hours == Decimal("8")
    assert quotes[0].funding_rate == Decimal("0.0008")
    with pytest.raises(ValueError, match="OKX tickers"):
        parse_okx({"code": "51000", "msg": "no"}, {"code": "0", "data": []}, {"code": "0", "data": []}, ["BTC"], cfg, "perp", "USDT", Decimal("8"))
