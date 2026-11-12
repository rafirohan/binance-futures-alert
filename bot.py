
import os
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL = "https://fapi.binance.com"
BOT_TOKEN = "9204599241:AAEHzZTAMCzy1VMYrm6UbTJ0vLhGPCNvyA0"
CHAT_ID = "5923577644"

THRESHOLD = 250
STATE_FILE = "state.json"

session = requests.Session()


def api_get(endpoint, params=None):
    url = BASE_URL + endpoint

    for attempt in range(3):
        try:
            r = session.get(url, params=params, timeout=25)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2)


def telegram_send(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    r = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=25
    )

    r.raise_for_status()

    if not r.json().get("ok"):
        raise RuntimeError("Telegram delivery failed")


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            return set(json.load(f))
    except (FileNotFoundError, ValueError):
        return set()


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(sorted(state), f)


def weekly_change(symbol, current_price):
    candles = api_get(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": "1h",
            "limit": 169
        }
    )

    if len(candles) < 169:
        return None

    old_price = float(candles[0][1])

    if old_price <= 0:
        return None

    return (current_price / old_price - 1) * 100


def main():
    print("Binance Futures Scanner started")

    info = api_get("/fapi/v1/exchangeInfo")

    symbols = {
        s["symbol"]
        for s in info["symbols"]
        if s["status"] == "TRADING"
        and s["contractType"] == "PERPETUAL"
        and s["quoteAsset"] == "USDT"
    }

    tickers = api_get("/fapi/v1/ticker/24hr")

    old_state = load_state()
    new_state = set()
    alerts = []

    jobs = {}

    with ThreadPoolExecutor(max_workers=12) as pool:

        for ticker in tickers:
            symbol = ticker["symbol"]

            if symbol not in symbols:
                continue

            price = float(ticker["lastPrice"])

            if price <= 0:
                continue

            change_24h = float(ticker["priceChangePercent"])

            if change_24h >= THRESHOLD:
                key = f"{symbol}:24h"
                new_state.add(key)

                if key not in old_state:
                    alerts.append(
                        f"🚀 {symbol} - 24H PUMP\n"
                        f"Change: +{change_24h:.2f}%\n"
                        f"Price: {price}\n"
                        f"Market: Binance USDT Futures"
                    )

            jobs[
                pool.submit(weekly_change, symbol, price)
            ] = (symbol, price)

        for future in as_completed(jobs):
            symbol, price = jobs[future]

            try:
                change_7d = future.result()
            except Exception as e:
                print(f"Weekly scan failed: {symbol}: {e}")
                continue

            if change_7d is None:
                continue

            if change_7d >= THRESHOLD:
                key = f"{symbol}:7d"
                new_state.add(key)

                if key not in old_state:
                    alerts.append(
                        f"🔥 {symbol} - 7 DAY PUMP\n"
                        f"Change: +{change_7d:.2f}%\n"
                        f"Price: {price}\n"
                        f"Market: Binance USDT Futures"
                    )

    # Send notifications before saving state
    for alert in alerts:
        telegram_send(
            "🚨 BINANCE FUTURES PUMP ALERT 🚨\n\n" + alert
        )
        print("Alert sent:", alert)

    save_state(new_state)

    print("Scan completed")
    print("New alerts:", len(alerts))


if __name__ == "__main__":
    main()
