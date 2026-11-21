"""Optional live diagnostics; prints structure only, not the full API response."""

from app.services.trader_price_catalog import (
    API_ROOT,
    _fetch_json,
    parse_trader_prices,
)


def describe(value):
    if isinstance(value, dict):
        return f"dict keys={list(value)[:8]}"
    if isinstance(value, list):
        return f"list length={len(value)}"
    return type(value).__name__


def report(name, payload):
    print(f"{name} root: {describe(payload)}")
    data = payload.get("data") if isinstance(payload, dict) else None
    print(f"{name} data: {describe(data)}")
    if isinstance(data, dict):
        section = data.get(name.lower())
        print(f"{name} data.{name.lower()}: {describe(section)}")


def main():
    mode = "regular"
    traders = _fetch_json(f"{API_ROOT}/{mode}/traders")
    items = _fetch_json(f"{API_ROOT}/{mode}/items")
    report("Traders", traders)
    report("Items", items)
    prices = parse_trader_prices(items, traders)
    print("Items with trader prices:", len(prices))
    gas = prices.get("590a3efd86f77437d351a25b", [])
    print("Gas Analyzer trader offers:", gas[:6])
    if len(prices) < 200:
        raise SystemExit("WARNING: Fewer than 200 item prices parsed")
    print("PASS: Live data parsed")


if __name__ == "__main__":
    main()
