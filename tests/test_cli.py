import json
from pathlib import Path

from cross_venue_arb.cli import main
from cross_venue_arb.models import ScanResult


def test_scan_once_json_stays_observe_only(monkeypatch, capsys, tmp_path):
    calls = {"n": 0}

    def fake_scan(config, venues):
        calls["n"] += 1
        return ScanResult(
            timestamp=__import__("datetime").datetime(2026, 10, 29, 12, 0, tzinfo=__import__("datetime").timezone.utc),
            requested_mode=config.mode,
            observe_only=True,
            orders_sent=0,
            quotes=[],
            spreads=[],
            venue_errors={},
            venue_warnings={},
        )

    monkeypatch.setattr("cross_venue_arb.cli.scan_once", fake_scan)
    log_path = tmp_path / "none.jsonl"
    code = main(
        ["scan", "--once", "--format", "json", "--log-path", str(log_path), "--mode", "live"]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert calls["n"] == 1
    payload = json.loads(captured.out)
    assert payload["observe_only"] is True
    assert payload["orders_sent"] == 0
    assert payload["requested_mode"] == "live"
    assert "orders will not be sent" in captured.err
    assert "Order routing stays off" in captured.err
    assert not log_path.exists()


def test_safety_check_and_venues_and_bad_symbol(capsys):
    assert main(["safety-check"]) == 0
    text = capsys.readouterr().out
    assert "fail closed" in text
    assert "no order sent" in text
    assert "order_router=absent" in text

    assert main(["venues"]) == 0
    listing = capsys.readouterr().out
    assert "HL" in listing
    assert "paper" in listing

    assert main(["scan", "--once", "--symbols", "BTC/USDT"]) == 2
    assert "config error" in capsys.readouterr().err


def test_package_has_no_order_routes_or_manipulation_helpers():
    root = Path(__file__).resolve().parents[1] / "cross_venue_arb"
    text = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))
    lowered = text.lower()
    for banned in ("/api/v3/order", "/fapi/v1/order", "/api/v1/order", "wash", "spoof", "self-trade", "self_trade"):
        assert banned not in lowered
    scanner = (root / "scanner.py").read_text(encoding="utf-8")
    assert "submit_order" not in scanner
    assert "live_trading" not in scanner
    for path in (root / "venues").rglob("*.py"):
        assert "submit_order" not in path.read_text(encoding="utf-8")
