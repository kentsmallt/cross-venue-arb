from datetime import datetime, timezone
from decimal import Decimal

from cross_venue_arb.config import default_config
from cross_venue_arb.models import VenueResult, try_quote
from cross_venue_arb.output import append_opportunities, render_json, render_table
from cross_venue_arb.scanner import scan_once


def _quote(venue, bid, ask, ccy):
    quote = try_quote(
        venue=venue,
        canonical_symbol="BTC",
        venue_symbol="BTC",
        kind="perp",
        quote_ccy=ccy,
        bid=Decimal(bid),
        ask=Decimal(ask),
        bid_size=Decimal("1"),
        ask_size=Decimal("1"),
        funding_rate=Decimal("0"),
        funding_interval_hours=Decimal("1"),
        price_source="test",
    )
    assert quote is not None
    return quote


class _Ok:
    name = "hyperliquid"

    def fetch(self, symbols, timeout):
        return VenueResult(self.name, [_quote("hyperliquid", "99", "100", "USD")])


class _Also:
    name = "backpack"

    def fetch(self, symbols, timeout):
        return VenueResult(self.name, [_quote("backpack", "101", "102", "USDC")], warnings=["slow"])


class _Down:
    name = "okx"

    def fetch(self, symbols, timeout):
        raise RuntimeError("timeout")


def test_one_venue_down_does_not_drop_the_others():
    cfg = default_config()
    result = scan_once(cfg, [_Ok(), _Also(), _Down()])
    assert result.observe_only is True
    assert result.orders_sent == 0
    assert result.requested_mode == "paper"
    assert {quote.venue for quote in result.quotes} == {"hyperliquid", "backpack"}
    assert "timeout" in result.venue_errors["okx"]
    assert result.venue_warnings["backpack"] == ["slow"]
    assert any(row.buy_venue == "hyperliquid" and row.sell_venue == "backpack" for row in result.spreads)
    assert all(row.buy_venue != row.sell_venue for row in result.spreads)
    text = render_table(result, cfg)
    assert "orders_sent=0" in text
    assert "observe_only=true" in text
    payload = render_json(result, pretty=False)
    assert '"orders_sent":0' in payload
    assert '"observe_only":true' in payload


def test_opportunity_log_skips_unattractive_rows(tmp_path):
    cfg = default_config()
    cfg.log_path = str(tmp_path / "opps.jsonl")
    result = scan_once(cfg, [_Ok(), _Also()])
    written = append_opportunities(result, cfg.log_path)
    assert written == 1
    lines = (tmp_path / "opps.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert '"buy_venue":"hyperliquid"' in lines[0]
    assert '"orders_sent":0' in lines[0]
    assert append_opportunities(result, "") == 0


def test_empty_scan_has_no_orders():
    cfg = default_config()
    result = scan_once(cfg, [])
    assert result.quotes == []
    assert result.orders_sent == 0
    assert result.venue_errors["_"] == "no venues enabled"
    result.timestamp = datetime(2026, 10, 29, tzinfo=timezone.utc)
    assert "2026-10-29T00:00:00Z" in render_table(result, cfg)
