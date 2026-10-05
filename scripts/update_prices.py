#!/usr/bin/env python3
"""
Collects live prices from TGJU (with retry + fallback) and keeps last 48h snapshots.
"""
import json
import sys
import time
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

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
RETRY_DELAY = 8


def to_number(val, force_float=False):
    """Safely convert price string to number (int or float)."""
    if val is None:
        return 0.0 if force_float else 0
    s = str(val).replace(",", "").replace(" ", "").strip()
    if not s:
        return 0.0 if force_float else 0
    try:
        f = float(s)
        if force_float:
            return f
        if f == int(f):
            return int(f)
        return f
    except Exception:
        return 0.0 if force_float else 0


def http_get(url, timeout=20):
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def parse_market_tmp(data):
    indicators = data.get("response", {}).get("indicators", [])
    result = {}
    for item in indicators:
        name = item.get("name")
        if name not in KEYS:
            continue
        
        if name == "ons":
            raw = to_number(item.get("p"), force_float=True)
            price, unit = raw, "USD"
        else:
            raw = to_number(item.get("p"))
            price, unit = round(raw / 10), "Toman"
            
        result[name] = {
            "label": LABELS.get(name, name),
            "price": price,
            "raw": raw,
            "unit": unit,
            "change_pct": item.get("dp"),
            "direction": item.get("dt"),
            "time": item.get("t"),
        }
    return result


def parse_ajax_json(data):
    current = data.get("current", {})
    result = {}
    for name in KEYS:
        node = current.get(name)
        if not node:
            continue
            
        if name == "ons":
            raw = to_number(node.get("p"), force_float=True)
            price, unit = raw, "USD"
        else:
            raw = to_number(node.get("p"))
            price, unit = round(raw / 10), "Toman"
            
        result[name] = {
            "label": LABELS.get(name, name),
            "price": price,
            "raw": raw,
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
                print(f"[try {attempt}] GET {url[:70]}...")
                status, body = http_get(url)
                print(f"  status={status}, len={len(body)}")
                data = json.loads(body)

                if "response" in data and "indicators" in data.get("response", {}):
                    result = parse_market_tmp(data)
                elif "current" in data:
                    result = parse_ajax_json(data)
                else:
                    print("  unknown structure, keys:", list(data.keys())[:8])
                    continue

                if result:
                    print(f"  parsed {len(result)} items")
                    return result
                print("  parsed 0 items")
            except Exception as e:
                last_error = e
                print(f"  error: {e}")
        if attempt < MAX_RETRIES:
            print(f"Waiting {RETRY_DELAY}s...")
            time.sleep(RETRY_DELAY)
    raise RuntimeError(f"All endpoints failed. Last: {last_error}")


def load_history():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"Load warning: {e}")
    return {"updated_at": None, "keys": KEYS, "labels": LABELS, "snapshots": []}


def save_history(history):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"Saved → {DATA_FILE}")


def main():
    now = datetime.now(timezone.utc)
    print(f"=== {now.isoformat()} ===")
    print(f"Data file: {DATA_FILE}")

    try:
        current = fetch_prices()
    except Exception as e:
        print(f"FATAL: {e}")
        traceback.print_exc()
        return 1

    if not current:
        print("No prices – abort")
        return 1

    print("Latest prices:")
    for k, v in current.items():
        print(f"  {v['label']}: {v['price']} {v['unit']}")

    history = load_history()
    snapshots = history.get("snapshots") or []

    snapshots.append({
        "ts": int(now.timestamp()),
        "iso": now.isoformat(),
        "prices": current,
    })

    cutoff = int((now - timedelta(hours=KEEP_HOURS)).timestamp())
    snapshots = [s for s in snapshots if s.get("ts", 0) >= cutoff]

    cleaned, last_ts = [], 0
    for s in sorted(snapshots, key=lambda x: x.get("ts", 0)):
        if not cleaned or s["ts"] - last_ts >= 50 * 60:
            cleaned.append(s)
            last_ts = s["ts"]
        else:
            cleaned[-1] = s
            last_ts = s["ts"]

    history = {
        "updated_at": now.isoformat(),
        "keys": KEYS,
        "labels": LABELS,
        "snapshots": cleaned,
    }
    save_history(history)
    print(f"Done. Snapshots: {len(cleaned)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
