"""Text table, JSON documents, and opportunity JSONL."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

from cross_venue_arb.config import AppConfig
from cross_venue_arb.models import ScanResult, Spread

_LABELS = {
    "hyperliquid": "HL",
    "binance_um": "BIN-P",
    "binance_spot": "BIN-S",
    "backpack": "BP",
    "okx": "OKX",
}


def venue_label(name: str) -> str:
    return _LABELS.get(name, name)


def render_summary(result: ScanResult, config: AppConfig) -> str:
    counts: dict[str, int] = {}
    for quote in result.quotes:
        counts[quote.venue] = counts.get(quote.venue, 0) + 1
    enabled = [name for name, spec in config.venues.items() if spec.enabled]
    parts = [
        result.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        f"mode={result.requested_mode}",
        "observe_only=true" if result.observe_only else "observe_only=false",
        f"orders_sent={result.orders_sent}",
    ]
    venue_bits = []
    for name in enabled:
        if name in result.venue_errors:
            venue_bits.append(f"{venue_label(name)}=ERR")
        else:
            venue_bits.append(f"{venue_label(name)}={counts.get(name, 0)}")
    parts.append("venues " + ",".join(venue_bits))
    parts.append(f"opportunities={len(result.opportunities)}")
    lines = [" | ".join(parts)]
    for name, message in sorted(result.venue_errors.items()):
        lines.append(f"error {venue_label(name)}: {message}")
    for name, warnings in sorted(result.venue_warnings.items()):
        for warning in warnings:
            lines.append(f"warn {venue_label(name)}: {warning}")
    if config.top > 0 and len(result.spreads) > config.top:
        lines.append(f"showing top {config.top} of {len(result.spreads)} spreads")
    return "\n".join(lines)


def render_table(result: ScanResult, config: AppConfig) -> str:
    rows = result.spreads if config.top <= 0 else result.spreads[: config.top]
    header = (
        "SYM",
        "BUY",
        "SELL",
        "KIND",
        "BUY_ASK",
        "SELL_BID",
        "GROSS",
        "FEE",
        "FUND",
        "BUF",
        "NET",
        "FLAGS",
    )
    body = [header]
    for row in rows:
        body.append(
            (
                row.canonical_symbol,
                venue_label(row.buy_venue),
                venue_label(row.sell_venue),
                _kind(row),
                _px(row.buy_ask),
                _px(row.sell_bid),
                _bps(row.gross_bps),
                _bps(row.fee_bps),
                _bps(row.funding_bps),
                _bps(row.buffer_bps),
                _bps(row.net_bps),
                _flags(row),
            )
        )
    widths = [max(len(record[index]) for record in body) for index in range(len(header))]
    numeric = {4, 5, 6, 7, 8, 9, 10}
    lines = [render_summary(result, config), ""]
    for record in body:
        cells = []
        for index, cell in enumerate(record):
            if index in numeric:
                cells.append(cell.rjust(widths[index]))
            else:
                cells.append(cell.ljust(widths[index]))
        lines.append("  ".join(cells))
    if not rows:
        lines.append("(no comparable quotes)")
    return "\n".join(lines)


def scan_document(result: ScanResult) -> dict[str, Any]:
    return {
        "ts": result.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "requested_mode": result.requested_mode,
        "observe_only": result.observe_only,
        "orders_sent": result.orders_sent,
        "venue_errors": result.venue_errors,
        "venue_warnings": result.venue_warnings,
        "quotes": [quote.to_dict() for quote in result.quotes],
        "spreads": [row.to_dict() for row in result.spreads],
        "opportunities": [row.to_dict() for row in result.opportunities],
    }


def render_json(result: ScanResult, pretty: bool) -> str:
    if pretty:
        return json.dumps(scan_document(result), indent=2)
    return json.dumps(scan_document(result), separators=(",", ":"))


def append_opportunities(result: ScanResult, log_path: str) -> int:
    rows = result.opportunities
    if not log_path or not rows:
        return 0
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = result.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            record = {
                "ts": stamped,
                "requested_mode": result.requested_mode,
                "observe_only": True,
                "orders_sent": 0,
                **row.to_dict(),
            }
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return len(rows)


def write_scan(result: ScanResult, config: AppConfig, stdout: TextIO, stderr: TextIO) -> None:
    if config.output_format == "json":
        pretty = config.once
        print(render_json(result, pretty=pretty), file=stdout)
        print(render_summary(result, config), file=stderr)
        return
    print(render_table(result, config), file=stdout)
    print(file=stdout)


def _kind(row: Spread) -> str:
    if row.strategy == "perp_cross":
        return "perp"
    if row.strategy == "spot_cross":
        return "spot"
    return "basis"


def _flags(row: Spread) -> str:
    flags: list[str] = []
    if row.opportunity:
        flags.append("opp")
    if row.suspect:
        flags.append("suspect")
    if row.thin:
        flags.append("thin")
    if not row.funding_known:
        flags.append("fund?")
    if row.strategy == "basis":
        flags.append("basis")
    if row.quote_fx:
        flags.append("fx")
    return ",".join(flags) if flags else "-"


def _bps(value: Decimal) -> str:
    return f"{value:.2f}"


def _px(value: Decimal) -> str:
    if value >= 1000:
        return f"{value:.2f}"
    if value >= 1:
        return f"{value:.4f}"
    return f"{value:.6f}"
