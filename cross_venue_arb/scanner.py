"""One scan pass. Each venue is isolated; a failure does not stop the others."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Protocol

from cross_venue_arb.config import AppConfig
from cross_venue_arb.models import ScanResult, VenueResult
from cross_venue_arb.spreads import build_spreads


class Venue(Protocol):
    name: str

    def fetch(self, canonical_symbols: list[str], timeout: float) -> VenueResult: ...


def scan_once(config: AppConfig, venues: list[Venue]) -> ScanResult:
    errors: dict[str, str] = {}
    warnings: dict[str, list[str]] = {}
    quotes = []
    if not venues:
        errors["_"] = "no venues enabled"
    else:
        workers = max(1, min(8, len(venues)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(venue.fetch, list(config.symbols), config.request_timeout_seconds): venue
                for venue in venues
            }
            for future in as_completed(futures):
                venue = futures[future]
                try:
                    result = future.result()
                except Exception as exc:
                    errors[venue.name] = f"{type(exc).__name__}: {exc}"
                    continue
                if result.error:
                    errors[result.venue] = result.error
                if result.warnings:
                    warnings[result.venue] = list(result.warnings)
                quotes.extend(result.quotes)
    return ScanResult(
        timestamp=datetime.now(timezone.utc),
        requested_mode=config.mode,
        observe_only=True,
        orders_sent=0,
        quotes=quotes,
        spreads=build_spreads(quotes, config),
        venue_errors=errors,
        venue_warnings=warnings,
    )
