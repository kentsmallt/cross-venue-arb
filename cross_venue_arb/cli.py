"""CLI. `scan` only reads public market data."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Sequence, TextIO

from cross_venue_arb import __version__
from cross_venue_arb.config import (
    ConfigError,
    apply_cli,
    default_config,
    effective_interval,
    load_config,
)
from cross_venue_arb.output import append_opportunities, venue_label, write_scan
from cross_venue_arb.safety import CONFIRM_ENV, LiveTradingBlocked, live_gates, submit_order
from cross_venue_arb.scanner import scan_once
from cross_venue_arb.venues import build_venues


def main(argv: Sequence[str] | None = None, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = _parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 2
    try:
        if args.command == "scan":
            return _scan(args, out, err)
        if args.command == "venues":
            return _venues(args, out)
        if args.command == "safety-check":
            return _safety(args, out)
    except ConfigError as exc:
        print(f"config error: {exc}", file=err)
        return 2
    print("unknown command", file=err)
    return 2


def _scan(args: argparse.Namespace, stdout: TextIO, stderr: TextIO) -> int:
    config = _config_from_args(args)
    venues = build_venues(config)
    _print_banner(config, stderr if config.output_format == "json" else stdout)
    if config.mode == "live":
        print(
            "live mode was requested. Order routing stays off and this process only observes.",
            file=stderr,
        )
    interval = effective_interval(config)
    if interval != config.interval_seconds:
        print(
            f"interval raised to {interval:.0f}s (minimum polite poll).",
            file=stderr,
        )
    try:
        while True:
            result = scan_once(config, venues)
            append_opportunities(result, config.log_path)
            write_scan(result, config, stdout, stderr)
            if config.once:
                return 0 if result.quotes else 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("stopped", file=stderr)
        return 0


def _venues(args: argparse.Namespace, stdout: TextIO) -> int:
    config = _config_from_args(args)
    print(f"{'VENUE':<14} {'ON':<4} {'KIND':<6} {'CCY':<6} {'TAKER':>7} {'MAKER':>7}  URL", file=stdout)
    for spec in config.venues.values():
        state = "yes" if spec.enabled else "no"
        print(
            f"{venue_label(spec.name):<14} {state:<4} {spec.kind:<6} {spec.quote_ccy:<6} "
            f"{spec.taker_fee_bps:>6}b {spec.maker_fee_bps:>6}b  {spec.base_url}",
            file=stdout,
        )
    print(
        f"fee_role={config.fee_role}  buffer={config.fee_buffer_bps}bp  "
        f"slippage={config.slippage_bps}bp  stablecoin_buffer={config.stablecoin_buffer_bps}bp  "
        f"funding_horizon={config.funding_horizon_hours}h  mode={config.mode}",
        file=stdout,
    )
    return 0


def _safety(args: argparse.Namespace, stdout: TextIO) -> int:
    config = _config_from_args(args)
    gates = live_gates(config)
    print(f"requested_mode={config.mode}", file=stdout)
    print(f"live_trading_enabled={str(config.live_trading_enabled).lower()}", file=stdout)
    print(f"confirm_env={CONFIRM_ENV}", file=stdout)
    print("order_router=absent", file=stdout)
    print("observe_only=true", file=stdout)
    if gates:
        print("gates_closed=" + "; ".join(gates), file=stdout)
    else:
        print("gates_closed=(none, router still absent)", file=stdout)
    try:
        submit_order(config, {"symbol": "BTC", "side": "buy", "qty": "0"})
    except LiveTradingBlocked as exc:
        print(f"result={exc}", file=stdout)
        return 0
    print("result=unexpectedly allowed", file=stdout)
    return 3


def _config_from_args(args: argparse.Namespace):
    cfg = load_config(args.config) if getattr(args, "config", None) else default_config()
    require = None
    if getattr(args, "require_funding", False):
        require = True
    if getattr(args, "allow_unknown_funding", False):
        require = False
    return apply_cli(
        cfg,
        symbols=getattr(args, "symbols", None),
        interval=getattr(args, "interval", None),
        min_net_bps=getattr(args, "min_net_bps", None),
        fee_buffer_bps=getattr(args, "fee_buffer_bps", None),
        slippage_bps=getattr(args, "slippage_bps", None),
        stablecoin_buffer_bps=getattr(args, "stablecoin_buffer_bps", None),
        funding_horizon_hours=getattr(args, "funding_horizon_hours", None),
        min_top_notional_usd=getattr(args, "min_top_notional_usd", None),
        fee_role=getattr(args, "fee_role", None),
        log_path=getattr(args, "log_path", None),
        output_format=getattr(args, "format", None),
        venues=getattr(args, "venues", None),
        mode=getattr(args, "mode", None),
        once=bool(getattr(args, "once", False)),
        top=getattr(args, "top", None),
        require_funding=require,
    )


def _print_banner(config, stream: TextIO) -> None:
    enabled = ",".join(spec.name for spec in config.venues.values() if spec.enabled)
    print(
        f"cross-venue-arb {__version__} | observe-only | orders will not be sent",
        file=stream,
    )
    print(
        f"symbols={','.join(config.symbols)} venues={enabled} "
        f"fees={config.fee_role} fee_buffer={config.fee_buffer_bps}bp "
        f"slippage={config.slippage_bps}bp stablecoin_buffer={config.stablecoin_buffer_bps}bp "
        f"funding_horizon={config.funding_horizon_hours}h min_net={config.min_net_bps}bp",
        file=stream,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cross-venue-arb",
        description="Observe-only cross-venue crypto spread scanner. Does not send orders.",
    )
    parser.add_argument("--version", action="version", version=f"cross-venue-arb {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="poll public books and print spreads")
    _add_common(scan)
    scan.add_argument("--once", action="store_true", help="scan a single time and exit")
    scan.add_argument("--interval", type=float, default=None, help="seconds between scans (min 2)")
    scan.add_argument("--symbols", help="comma-separated canonical symbols, e.g. BTC,ETH,SOL")
    scan.add_argument("--venues", help="comma-separated venues to enable (others turn off)")
    scan.add_argument("--min-net-bps", dest="min_net_bps", help="log rows at or above this net bps")
    scan.add_argument("--fee-buffer-bps", dest="fee_buffer_bps", help="extra fee uncertainty in bps")
    scan.add_argument("--slippage-bps", dest="slippage_bps", help="slippage buffer in bps")
    scan.add_argument("--stablecoin-buffer-bps", dest="stablecoin_buffer_bps")
    scan.add_argument("--funding-horizon-hours", dest="funding_horizon_hours")
    scan.add_argument("--min-top-notional-usd", dest="min_top_notional_usd")
    scan.add_argument("--fee-role", choices=("taker", "maker"))
    scan.add_argument("--format", choices=("table", "json"))
    scan.add_argument("--log-path", dest="log_path", help="JSONL path; empty string disables")
    scan.add_argument("--top", type=int, default=None, help="table rows to show; 0 shows all")
    scan.add_argument("--mode", choices=("paper", "live"), help="live still does not send orders")
    scan.add_argument(
        "--allow-unknown-funding",
        action="store_true",
        help="count a row as an opportunity even if perp funding is missing",
    )
    scan.add_argument(
        "--require-funding",
        action="store_true",
        help="require known funding before logging an opportunity (default)",
    )

    venues = sub.add_parser("venues", help="show venues, fee assumptions, and URLs")
    _add_common(venues)

    safety = sub.add_parser("safety-check", help="show that order routing fails closed")
    _add_common(safety)
    safety.add_argument("--mode", choices=("paper", "live"))
    return parser


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="TOML config path (optional; defaults are built in)")
