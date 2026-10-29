# cross-venue-arb

Observe-only scanner for cross-venue crypto price spreads. It reads public order books and funding from Hyperliquid perps, Backpack perps, OKX USDT swaps, and Binance (USD-M perps, plus optional spot), then prints the spread after a fee, funding, and buffer estimate.

It does not place, amend, or cancel orders. Paper / dry-run is the only behavior. There is no order router in this version. Turning on the live flag still fails closed and sends nothing.

This is research software, not a trading system and not financial advice.

## Quick start

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

python -m cross_venue_arb scan --once
python -m cross_venue_arb scan --symbols BTC,ETH,SOL --interval 10
python -m cross_venue_arb scan --once --format json
python -m cross_venue_arb venues
python -m cross_venue_arb safety-check
```

No API keys are required. Public market data only.

A scan writes a table to stdout and appends rows that clear the net threshold to `logs/opportunities.jsonl`. Set `--log-path ""` to skip the file. `--format json` prints one JSON document per scan (pretty when `--once`, one line per scan in a loop). Diagnostics stay on stderr in JSON mode so stdout stays machine-readable.

Copy `config.example.toml` to `config.toml` and pass `--config config.toml` when you want different fees, symbols, or venues. Built-in defaults match that example, so the file is optional.

## What a row means

For each symbol and each ordered pair of venues the scanner asks: buy venue A at its ask, sell venue B at its bid.

```text
gross_bps   = (sell_bid - buy_ask) / buy_ask * 10_000
fee_bps     = fee(buy) + fee(sell)          # taker unless you set fee_role = "maker"
funding_bps = (hourly_buy - hourly_sell) * funding_horizon_hours * 10_000
buffer_bps  = fee_buffer + slippage + stablecoin_buffer   # last term only if quote currencies differ
net_bps     = gross_bps - fee_bps - funding_bps - buffer_bps
```

Positive funding means longs pay shorts. The buy leg is the long and the sell leg is the short, so a higher funding rate on the long is a cost and a higher funding rate on the short is a credit. Rates are converted to an hourly rate (`rate / interval_hours`) before the horizon is applied. The default horizon is 1 hour, not a full day and not annualized.

An opportunity is a row whose net is at least `--min-net-bps` (default 0) and which is not thin, not suspect, and not missing perp funding. Those rows are the ones appended to the JSONL log. The table still shows the other rows.

Flags:

| Flag | Meaning |
| --- | --- |
| `opp` | Clears the net threshold and the filters below |
| `fx` | USD/USDC leg against a USDT leg; stablecoin buffer was added |
| `basis` | One leg is spot. Borrow / locate cost is not modeled |
| `fund?` | Perp funding was missing and was treated as zero |
| `thin` | Top-of-book notional is below `--min-top-notional-usd`, or size is unknown while that floor is set |
| `suspect` | Venue mids differ by more than `max_mid_divergence_bps` (default 500). Usually a bad symbol map or a broken book, not a trade |

`--fee-role maker` swaps in maker fees. The prices are still touch prices (you cross the spread), so maker fees overstate the edge. Leave the default `taker`.

## Venues

| Venue | Default | Market | Quote group | Default interval | Touch source |
| --- | --- | --- | --- | --- | --- |
| `hyperliquid` | on | perp | USD (grouped with USDC) | 1h | L2 top, else published impact prices |
| `binance_um` | on | USD-M perp | USDT | 8h assumed | book ticker + premium index |
| `binance_spot` | off | spot | USDT | none | `data-api.binance.vision` book ticker |
| `backpack` | on | perp | USDC | 1h | depth (best bid/ask, book is sorted low to high) + mark prices |
| `okx` | on | USDT swap | USDT | from funding timestamps, else 8h | ticker; contract size converted with `ctVal` |

`--venues hl,bp,okx` enables only those names (`hl`, `binance`, `binance-perp`, `binance-spot`, `bp`, `okx` are accepted). Binance USD-M is requested from `https://fapi.binance.com`. Some regions get HTTP 451. That venue is reported as an error and the scan continues with whoever answered.

Symbols are canonical tickers such as `BTC`. They map to `BTC` on Hyperliquid, `BTCUSDT` on Binance, `BTC_USDC_PERP` on Backpack, and `BTC-USDT-SWAP` on OKX. Odd listings (Hyperliquid `kPEPE`, Binance `1000PEPE`) belong in `[symbol_map.<venue>]`. Names that are not letters and digits are rejected so they cannot be dropped into a URL.

The poll interval is at least 2 seconds.

## Fee assumptions

Defaults are **base-tier estimates** so a raw price gap is not mistaken for edge. They are not fetched from the venues and they go stale when a venue changes its schedule or when your account is not on the base tier. Check the current fee page and override `taker_fee_bps` / `maker_fee_bps` before you trust a number.

| Venue | Taker default | Maker default | Notes |
| --- | --- | --- | --- |
| Hyperliquid perps | 4.5 bp | 1.5 bp | Published base tier is about 0.045% / 0.015% |
| Binance USD-M | 5 bp | 2 bp | VIP 0 is often 0.050% / 0.020%. Interval is assumed 8h for every symbol; some contracts fund every 1h or 4h |
| Binance spot | 10 bp | 10 bp | VIP 0 without a fee discount. Off unless you enable it |
| Backpack perps | 5 bp | 2 bp | Confirm the current perps schedule; funding is modeled as hourly |
| OKX USDT swap | 5 bp | 2 bp | VIP 0 is often 0.050% / 0.020% |

On top of those, the default model subtracts 1 bp of fee uncertainty and 1 bp of slippage, and another 1 bp when the two quotes are not in the same stablecoin group (USD and USDC count as one group; USDT does not). USDT/USDC can move more than 1 bp. Set `stablecoin_buffer_bps` to whatever haircut you want, including 0.

Funding on a spot leg is zero. A spot-versus-perp row is marked `basis` because the short stock borrow, or the cash you lock in a long spot hedge, is not priced.

## Safety

- Default `mode` is `paper`. Default `live_trading_enabled` is `false`.
- `live_trading_enabled` has to be a TOML boolean. A string, a missing key, or a CLI typo does not turn it on. There is no CLI switch that sets it.
- `scan` never calls the order gate. It only reads public books.
- `safety-check` calls `submit_order`, which raises before any network call. It refuses when any gate is shut. If `mode = "live"`, `live_trading_enabled = true`, and `ARB_LIVE_TRADING_CONFIRM=I_UNDERSTAND_LIVE_TRADING` are all set, it still refuses, because this version has no order client.
- The process does not load `.env` files. Nothing secret belongs in the repo. `.env.example` documents the confirm variable and is not required to scan.
- The scanner does not place resting orders, does not trade against itself, and is not a tool for wash trading or spoofing. A venue is never compared with itself.

```bash
python -m cross_venue_arb safety-check
python -m cross_venue_arb scan --mode live --once   # still observe-only
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Tests are offline. They cover the spread identity, funding-interval normalization, the fail-closed order gate, config parsing, and fixture parsers for each venue.

## Risk disclaimer

Crypto prices move, books update faster than this poller, and a printed spread is not a fill. Quotes can be stale, locked, thin, or wrong. Fees, VIP tiers, funding intervals, and rebates change. Hyperliquid impact prices are not the same as the touch. Backpack depth snapshots are large and slightly delayed. OKX sizes are converted from contracts. Binance USD-M funding is modeled with a flat 8 hour interval. USD, USDC, and USDT are not the same asset. Perpetual positions can be liquidated or auto-deleveraged. Spot versus perp basis can last longer than the funding you modeled. Exchange APIs fail, rate-limit, and geo-block.

Nothing in this repository is an offer to trade, a recommendation, or financial, investment, or legal advice. You can lose money if you trade on this output yourself. The authors and contributors are not liable for trading losses or for decisions you make after reading a table.
