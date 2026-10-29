from decimal import Decimal
from pathlib import Path

import pytest

from cross_venue_arb.config import (
    ConfigError,
    apply_cli,
    default_config,
    effective_interval,
    load_config,
    venue_symbol,
)


ROOT = Path(__file__).resolve().parents[1]


def test_example_config_matches_defaults():
    loaded = load_config(ROOT / "config.example.toml")
    defaults = default_config()
    assert loaded.mode == defaults.mode == "paper"
    assert loaded.live_trading_enabled is False
    assert loaded.symbols == defaults.symbols
    assert loaded.interval_seconds == defaults.interval_seconds
    assert loaded.min_net_bps == defaults.min_net_bps
    assert loaded.fee_buffer_bps == defaults.fee_buffer_bps
    assert loaded.slippage_bps == defaults.slippage_bps
    assert loaded.stablecoin_buffer_bps == defaults.stablecoin_buffer_bps
    assert loaded.funding_horizon_hours == defaults.funding_horizon_hours
    assert loaded.min_top_notional_usd == defaults.min_top_notional_usd
    assert loaded.max_mid_divergence_bps == defaults.max_mid_divergence_bps
    assert loaded.fee_role == defaults.fee_role
    assert loaded.require_funding is True
    assert loaded.log_path == defaults.log_path
    assert loaded.output_format == "table"
    assert loaded.symbol_map == {}
    for name, spec in defaults.venues.items():
        other = loaded.venues[name]
        assert other.enabled == spec.enabled
        assert other.kind == spec.kind
        assert other.quote_ccy == spec.quote_ccy
        assert other.taker_fee_bps == spec.taker_fee_bps
        assert other.maker_fee_bps == spec.maker_fee_bps
        assert other.funding_interval_hours == spec.funding_interval_hours
        assert other.base_url == spec.base_url


def test_partial_toml_overrides_and_symbol_map(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
        symbols = ["btc"]
        fee_buffer_bps = "3.5"
        [venues.okx]
        enabled = false
        taker_fee_bps = "7"
        [symbol_map.hl]
        PEPE = "kPEPE"
        """,
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.symbols == ["BTC"]
    assert cfg.fee_buffer_bps == Decimal("3.5")
    assert cfg.venues["okx"].enabled is False
    assert cfg.venues["okx"].taker_fee_bps == Decimal("7")
    assert cfg.venues["hyperliquid"].enabled is True
    assert venue_symbol(cfg, "hyperliquid", "PEPE") == "kPEPE"
    assert venue_symbol(cfg, "binance_um", "BTC") == "BTCUSDT"
    assert venue_symbol(cfg, "backpack", "ETH") == "ETH_USDC_PERP"
    assert venue_symbol(cfg, "okx", "SOL") == "SOL-USDT-SWAP"


@pytest.mark.parametrize(
    "body",
    [
        'live_trading_enabled = "true"\n',
        'mode = "yolo"\n',
        'symbols = ["../BTC"]\n',
        'surprise = 1\n',
        '[venues.binance_um]\nbase_url = "http://169.254.169.254"\n',
        '[venues.nope]\nenabled = true\n',
        '[symbol_map.hyperliquid]\nBTC = "BTC/USDT"\n',
    ],
)
def test_bad_config_is_rejected(tmp_path: Path, body: str):
    path = tmp_path / "bad.toml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


def test_cli_overrides_do_not_arm_live_trading():
    cfg = default_config()
    apply_cli(
        cfg,
        symbols="btc,eth",
        venues="bp,hl",
        min_net_bps="2.5",
        once=True,
        mode="live",
        interval=1,
    )
    assert cfg.symbols == ["BTC", "ETH"]
    assert cfg.venues["backpack"].enabled is True
    assert cfg.venues["hyperliquid"].enabled is True
    assert cfg.venues["okx"].enabled is False
    assert cfg.venues["binance_um"].enabled is False
    assert cfg.min_net_bps == Decimal("2.5")
    assert cfg.mode == "live"
    assert cfg.live_trading_enabled is False
    assert cfg.once is True
    assert effective_interval(cfg) == 2.0


def test_missing_file():
    with pytest.raises(ConfigError):
        load_config("/tmp/does-not-exist-cross-venue-arb.toml")
