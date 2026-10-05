#!/usr/bin/env python3
"""
Fetches prices frequently and builds real hourly OHLC candles.
Runs every ~15 minutes via GitHub Actions.
Keeps last 48 hours of hourly candles.
"""
import json
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request

KEYS = [
    "geram18", "geram24", "sekee", "nim", "rob", "ons",
    "price_dollar_rl", "price_eur", "price_aed", "price_try",
]

LABELS = {
    "geram18": "طلای ۱۸ عیار",
    "geram24": "طلای ۲۴ عیار",
    "sekee": "سکه امامی",
    "nim": "نیم سکه",
    "rob": "ربع سکه",
    "ons": "انس طلا",
    "price_dollar_rl": "دلار آمریکا",
    "price_eur": "یورو",
    "price_aed": "درهم امارات",
    "price_try": "لیر ترکیه",
}

ENDPOINTS = [
    "https://api.tgju.org/v1/market/tmp?keys=" + ",".join(KEYS),
    "https://call1.tgju.org/ajax.json",
    "https://call2.tgju.org/ajax.json",
]

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "prices.json"
KEEP_HOURS = 48
MAX_RETRIES = 3
RETRY_DELAY = 6


def to_number(val):
    if val is None:
        return None
    s = str(val).replace(",", "").replace(" ", "").strip()
    if not s:
        return None
    try:
        f = float(s)
        return f
    except Exception:
        return None


def http_get(url, timeout=20):
    req = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    })
    with urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def parse_market_tmp(data):
    result = {}
    for item in data.get("response", {}).get("indicators", []):
        name = item.get("name")
        if name not in KEYS:
            continue
        raw = to_number(item.get("p"))
        if raw is None:
            continue
        if name == "ons":
            price, unit = round(raw, 2), "USD"
        else:
            price, unit = int(round(raw / 10)), "Toman"
        result[name] = {
            "label": LABELS.get(name, name),
            "price": price,
            "unit": unit,
            "change_pct": item.get("dp"),
            "direction": item.get("dt"),
            "time": item.get("t"),
        }
    return result


def parse_ajax_json(data):
    result = {}
    current = data.get("current", {})
    for name in KEYS:
        node = current.get(name)
        if not node:
            continue
        raw = to_number(node.get("p"))
        if raw is None:
            continue
        if name == "ons":
            price, unit = round(raw, 2), "USD"
        else:
            price, unit = int(round(raw / 10)), "Toman"
        result[name] = {
            "label": LABELS.get(name, name),
            "price": price,
            "unit": unit,
            "change_pct": node.get("dp"),
            "direction": node.get("dt"),
            "time": node.get("t"),
        }
    return result


def fetch_prices():
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        for url in ENDPOINTS:
            try:
                print(f"[try {attempt}] {url[:65]}...")
                status, body = http_get(url)
                data = json.loads(body)
                if "response" in data:
                    result = parse_market_tmp(data)
                elif "current" in data:
                    result = parse_ajax_json(data)
                else:
                    continue
                if result:
                    print(f"  OK – {len(result)} items")
                    return result
            except Exception as e:
                last_error = e
                print(f"  error: {e}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_DELAY)
    raise RuntimeError(f"All failed: {last_error}")


def hour_bucket(ts):
    """Return timestamp of the start of the hour (UTC)."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return int(dt.replace(minute=0, second=0, microsecond=0).timestamp())


def load_data():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict):
                    return d
        except Exception as e:
            print("Load warning:", e)
    return {
        "updated_at": None,
        "keys": KEYS,
        "labels": LABELS,
        "latest": {},
        "candles": {k: [] for k in KEYS},
    }


def save_data(data):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"Saved → {DATA_FILE}")


def update_candles(candles_dict, key, price, now_ts):
    """
    Maintain hourly OHLC candles for one symbol.
    - First price of the hour → sets Open, High, Low, Close
    - Later prices in same hour → update High, Low, Close
    """
    if price is None:
        return
    bucket = hour_bucket(now_ts)
    arr = candles_dict.setdefault(key, [])

    if arr and arr[-1]["ts"] == bucket:
        # update current hour candle
        c = arr[-1]
        c["h"] = max(c["h"], price)
        c["l"] = min(c["l"], price)
        c["c"] = price
    else:
        # new hour → new candle
        arr.append({
            "ts": bucket,
            "o": price,
            "h": price,
            "l": price,
            "c": price,
        })

    # keep only last KEEP_HOURS
    cutoff = now_ts - KEEP_HOURS * 3600
    candles_dict[key] = [c for c in arr if c["ts"] >= cutoff]


def main():
    now = datetime.now(timezone.utc)
    now_ts = int(now.timestamp())
    print(f"=== {now.isoformat()} ===")

    try:
        current = fetch_prices()
    except Exception as e:
        print("FATAL:", e)
        traceback.print_exc()
        return 1

    if not current:
        print("No data")
        return 1

    data = load_data()
    data["updated_at"] = now.isoformat()
    data["keys"] = KEYS
    data["labels"] = LABELS
    data["latest"] = current

    if "candles" not in data or not isinstance(data["candles"], dict):
        data["candles"] = {k: [] for k in KEYS}

    for key, info in current.items():
        update_candles(data["candles"], key, info["price"], now_ts)

    # ensure all keys exist
    for k in KEYS:
        data["candles"].setdefault(k, [])

    save_data(data)

    print("Latest:")
    for k, v in current.items():
        n = len(data["candles"].get(k, []))
        print(f"  {v['label']}: {v['price']} {v['unit']}  ({n} candles)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
