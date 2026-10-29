import pytest

from cross_venue_arb.config import default_config
from cross_venue_arb.safety import CONFIRM_ENV, CONFIRM_PHRASE, LiveTradingBlocked, submit_order


def test_defaults_are_paper_and_disabled():
    cfg = default_config()
    assert cfg.mode == "paper"
    assert cfg.live_trading_enabled is False


@pytest.mark.parametrize(
    ("mode", "enabled", "confirm"),
    [
        ("paper", False, None),
        ("live", False, None),
        ("paper", True, None),
        ("live", True, None),
        ("live", True, "yes"),
        ("paper", True, CONFIRM_PHRASE),
        ("live", False, CONFIRM_PHRASE),
    ],
)
def test_partial_gates_fail_closed(monkeypatch, mode, enabled, confirm):
    monkeypatch.delenv(CONFIRM_ENV, raising=False)
    if confirm is not None:
        monkeypatch.setenv(CONFIRM_ENV, confirm)
    cfg = default_config()
    cfg.mode = mode
    cfg.live_trading_enabled = enabled
    with pytest.raises(LiveTradingBlocked, match="no order sent"):
        submit_order(cfg, {"symbol": "BTC", "side": "buy", "qty": "1"})


def test_open_gates_still_have_no_router(monkeypatch):
    monkeypatch.setenv(CONFIRM_ENV, CONFIRM_PHRASE)
    cfg = default_config()
    cfg.mode = "live"
    cfg.live_trading_enabled = True
    with pytest.raises(LiveTradingBlocked, match="no order router"):
        submit_order(cfg, {"symbol": "BTC"})
