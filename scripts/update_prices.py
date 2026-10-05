#!/usr/bin/env python3
"""
Collects live prices from TGJU and keeps last 48 hours of hourly snapshots.
"""
import json
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

KEYS = [
    "geram18",          # طلای ۱۸ عیار
    "geram24",          # طلای ۲۴ عیار
    "sekee",            # سکه امامی
    "nim",              # نیم سکه
    "rob",              # ربع سکه
    "ons",              # انس طلا
    "price_dollar_rl",  # دلار آمریکا
    "price_eur",        # یورو
    "price_aed",        # درهم امارات
    "price_try",        # لیر ترکیه
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

API_URL = "https://api.tgju.org/v1/market/tmp?keys=" + ",".join(KEYS)
DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "prices.json"
KEEP_HOURS = 48


def fetch_prices():
    print(f"Requesting: {API_URL}")
    req = Request(
        API_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; iran-prices/1.1)",
            "Accept": "application/json",
        },
    )
    with urlopen(req, timeout=25) as resp:
        body = resp.read().decode("utf-8")
        print(f"HTTP status: {resp.status}, length: {len(body)}")
        data = json.loads(body)

    indicators = data.get("response", {}).get("indicators", [])
    if not indicators:
        print("Warning: no indicators in response")
        print("Response keys:", list(data.keys()))
        return {}

    result = {}
    for item in indicators:
        name = item.get("name")
        if name not in KEYS:
            continue
        try:
            raw = int(str(item.get("p", "0")).replace(",", "").strip())
        except Exception:
            raw = 0

        if name == "ons":
            price = raw
            unit = "USD"
        else:
            price = round(raw / 10)
            unit = "Toman"

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


def load_history():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"Could not load existing file: {e}")
    return {"updated_at": None, "keys": KEYS, "labels": LABELS, "snapshots": []}


def save_history(history):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"Saved to {DATA_FILE}")


def main():
    now = datetime.now(timezone.utc)
    print(f"=== Start {now.isoformat()} ===")
    print(f"Data file path: {DATA_FILE}")

    try:
        current = fetch_prices()
    except (URLError, HTTPError) as e:
        print(f"Network error: {e}")
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"Fetch error: {e}")
        traceback.print_exc()
        return 1

    if not current:
        print("No prices fetched – aborting without update")
        return 1

    print(f"Fetched {len(current)} items:")
    for k, v in current.items():
        print(f"  {v['label']}: {v['price']} {v['unit']}")

    history = load_history()
    snapshots = history.get("snapshots") or []

    snapshot = {
        "ts": int(now.timestamp()),
        "iso": now.isoformat(),
        "prices": current,
    }
    snapshots.append(snapshot)

    # Keep last KEEP_HOURS
    cutoff_ts = int((now - timedelta(hours=KEEP_HOURS)).timestamp())
    snapshots = [s for s in snapshots if s.get("ts", 0) >= cutoff_ts]

    # Deduplicate: keep roughly one per hour
    cleaned = []
    last_ts = 0
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
    print(f"Done. Total snapshots kept: {len(cleaned)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
