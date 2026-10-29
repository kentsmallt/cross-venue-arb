"""Live order routing is fail-closed.

v0 has no order client. Public market-data scans never call this module.
`submit_order` is the only entry point that would have to exist before any
order could be sent, and it raises before doing I/O in every configuration.
"""

from __future__ import annotations

import os
from typing import Any

from cross_venue_arb.config import AppConfig

CONFIRM_ENV = "ARB_LIVE_TRADING_CONFIRM"
CONFIRM_PHRASE = "I_UNDERSTAND_LIVE_TRADING"


class LiveTradingBlocked(RuntimeError):
    """Raised instead of sending an order. Nothing was transmitted."""


def live_gates(config: AppConfig) -> list[str]:
    """Reasons the live gate is shut. Empty only when every explicit gate is open."""
    closed: list[str] = []
    if config.mode != "live":
        closed.append("mode is not live")
    if config.live_trading_enabled is not True:
        closed.append("live_trading_enabled is not true")
    if os.environ.get(CONFIRM_ENV) != CONFIRM_PHRASE:
        closed.append(f"{CONFIRM_ENV} is not set to the confirm phrase")
    return closed


def submit_order(config: AppConfig, order: dict[str, Any] | None = None) -> None:
    """Refuse to place, amend, or cancel an order.

    Gates default shut. A missing flag, a typo, or a partial opt-in all refuse.
    Even when every gate is open, v0 still refuses: there is no order router,
    and this function performs no network I/O. `order` is ignored on purpose.
    """
    del order  # never forwarded anywhere
    reasons = live_gates(config)
    if reasons:
        raise LiveTradingBlocked(
            "fail closed: no order sent (" + "; ".join(reasons) + ")"
        )
    raise LiveTradingBlocked(
        "fail closed: no order sent (live gates were open, but v0 has no order router)"
    )
