"""Venue adapters. Each module exposes a pure parser plus a fetch class."""

from cross_venue_arb.venues.backpack import BackpackVenue
from cross_venue_arb.venues.binance import BinanceSpotVenue, BinanceUmVenue
from cross_venue_arb.venues.hyperliquid import HyperliquidVenue
from cross_venue_arb.venues.okx import OkxVenue

__all__ = [
    "BackpackVenue",
    "BinanceSpotVenue",
    "BinanceUmVenue",
    "HyperliquidVenue",
    "OkxVenue",
]


def build_venues(config):
    classes = {
        "hyperliquid": HyperliquidVenue,
        "binance_um": BinanceUmVenue,
        "binance_spot": BinanceSpotVenue,
        "backpack": BackpackVenue,
        "okx": OkxVenue,
    }
    venues = []
    for name, cls in classes.items():
        spec = config.venues[name]
        if spec.enabled:
            venues.append(cls(config))
    return venues
