#!/usr/bin/env python3
"""
Collects live prices from TGJU and keeps last 48 hours of hourly snapshots.
"""
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import urlopen, Request

# Items we want to track (TGJU keys)
KEYS = [
    "geram18",          # طلای ۱۸ عیار
    "geram24",          # طلای ۲۴ عیار
    "sekee",            # سکه امامی (طرح جدید)
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
KEEP_HOURS = 48  # keep last 48 hours


def fetch_prices():
    req = Request(API_URL, headers={"User-Agent": "Mozilla/5.0 (compatible; iran-prices/1.0)"})
    with urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    indicators = data.get("response", {}).get("indicators", [])
    result = {}
    for item in indicators:
        name = item.get("name")
        if name not in KEYS:
            continue
        # p is in Rials for most items. We store both raw and toman.
        raw = int(str(item.get("p", "0")).replace(",", ""))
        # For gold ounce (ons) it is in USD, keep as is
        if name == "ons":
            price = raw  # actually comes as integer dollars*100 or similar? keep raw
            unit = "USD"
        else:
            price = round(raw / 10)  # Rial → Toman
            unit = "Toman"
        result[name] = {
            "label": LABELS.get(name, name),
            "price": price,
            "raw": raw,
            "unit": unit,
            "change_pct": item.get("dp"),
            "change_abs": item.get("d"),
            "direction": item.get("dt"),
            "open": item.get("o"),
            "high": item.get("h"),
            "low": item.get("l"),
            "time": item.get("t"),
        }
    return result


def load_history():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"updated_at": None, "snapshots": []}


def save_history(history):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def main():
    now = datetime.now(timezone.utc)
    print(f"[{now.isoformat()}] Fetching prices...")

    try:
        current = fetch_prices()
    except Exception as e:
        print("Fetch failed:", e)
        return 1

    history = load_history()
    snapshots = history.get("snapshots", [])

    # Add new snapshot
    snapshot = {
        "ts": int(now.timestamp()),
        "iso": now.isoformat(),
        "prices": current,
    }
    snapshots.append(snapshot)

    # Keep only last KEEP_HOURS
    cutoff = now - timedelta(hours=KEEP_HOURS)
    cutoff_ts = int(cutoff.timestamp())
    snapshots = [s for s in snapshots if s.get("ts", 0) >= cutoff_ts]

    # Avoid too frequent duplicates (keep max one per ~50 minutes)
    cleaned = []
    last_ts = 0
    for s in snapshots:
        if s["ts"] - last_ts >= 50 * 60 or not cleaned:
            cleaned.append(s)
            last_ts = s["ts"]
        else:
            # replace last one with newer
            cleaned[-1] = s
            last_ts = s["ts"]

    history = {
        "updated_at": now.isoformat(),
        "keys": KEYS,
        "labels": LABELS,
        "snapshots": cleaned,
    }
    save_history(history)
    print(f"Saved {len(cleaned)} snapshots. Latest prices:")
    for k, v in current.items():
        print(f"  {v['label']}: {v['price']} {v['unit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
