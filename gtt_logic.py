import os
import requests
import logging
import pandas as pd
from dotenv import load_dotenv
from token_manager import get_valid_upstox_access_token, generate_new_upstox_token


load_dotenv()

RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
RAPIDAPI_HOST = os.getenv("RAPIDAPI_HOST")

CSV_PATH = "data/Name-symbol-mapping.csv"
EXCHANGE_SEGMENT = "NSE_EQ"

LTP_ORDER_DIFF = 1.025
LTP_TRIGGER_DIFF = 0.0026
ORDER_TRIGGER_DIFF = 0.001

cmp_cache = {}

def get_cmp(kite, symbol, exchange):
    key = f"{exchange}:{symbol}"
    if key in cmp_cache:
        return cmp_cache[key]

    # Try from holdings
    try:
        for holding in kite.holdings():
            if holding["tradingsymbol"] == symbol and holding["exchange"] == exchange:
                cmp = float(holding["last_price"])
                cmp_cache[key] = cmp
                return cmp
    except Exception as e:
        logging.warning(f"Holdings fetch failed for {symbol}: {e}")

    # Fallback to Upstox
    try:
        cmp = get_cmp_from_upstox(symbol, exchange)
        if cmp:
            cmp_cache[key] = cmp
        return cmp
    except Exception as e:
        logging.error(f"Failed to fetch CMP from Upstox for {symbol}: {e}")
        return None



def get_cmp_from_upstox(symbol, exchange):
    try:
        access_token = get_valid_upstox_access_token()
        logging.debug(f"Access token retrieved for Upstox")

        instrument_key = get_instrument_key_from_csv(symbol, CSV_PATH, EXCHANGE_SEGMENT)
        logging.debug(f"Instrument key for {symbol}: {instrument_key}")
        if not instrument_key:
            logging.error(f"Instrument key not found for {symbol}")
            return None

        def fetch_ltp(token):
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {token}"
            }
            url = f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={instrument_key}"
            # logger.debug(f"Requesting LTP from Upstox: {url}")
            response = requests.get(url, headers=headers)
            logging.debug(f"Upstox response status: {response.status_code}")
            # logger.debug(f"Upstox response body: {response.text}")
            return response

        response = fetch_ltp(access_token)

        if response.status_code == 401:
            try:
                error_data = response.json()
                error_code = error_data.get("errors", [{}])[0].get("errorCode")
                if error_code == "UDAPI100050":
                    logging.info("Invalid Upstox token detected. Regenerating token...")
                    access_token = generate_new_upstox_token()
                    response = fetch_ltp(access_token)
            except Exception as e:
                logging.error(f"Error while handling token regeneration: {e}")
                return None

        data = response.json().get("data")
        if not data:
            logging.error(f"No 'data' field in Upstox response for {symbol}")
            return None

        actual_key = list(data.keys())[0]
        cmp = data[actual_key]["last_price"]
        logging.debug(f"Fetched CMP for {symbol} from Upstox: {cmp}")
        return cmp

    except Exception as e:
        logging.error(f"Failed to fetch CMP from Upstox for {symbol}: {e}")
        return None

def get_instrument_key_from_csv(symbol, csv_path, exchange_segment="NSE_EQ"):
    try:
        df = pd.read_csv(csv_path)
        df.columns = [col.strip() for col in df.columns]
        match = df[df['SYMBOL'].str.upper() == symbol.upper()]
        if not match.empty:
            isin = match.iloc[0]['ISIN NUMBER'].strip()
            return f"{exchange_segment}|{isin}"
        else:
            logging.error(f"Symbol '{symbol}' not found in the CSV.")
            return None
    except Exception as e:
        logging.error(f"Error reading CSV or extracting instrument key: {e}")
        return None

def trigger_price_and_adjust_order(order_price, ltp):
    min_diff = round(ltp * LTP_TRIGGER_DIFF, 4)  # 0.26%
    exact_diff = round(order_price * ORDER_TRIGGER_DIFF, 4)  # 0.1%

    if order_price < ltp:
        # Momentum order: order_price < trigger_price < ltp
        min_trigger = round(ltp - min_diff, 2)
        trigger = round(order_price + exact_diff, 2)
        if trigger < min_trigger:
            return order_price, trigger
        else:
            trigger = min_trigger
            order_price = round(trigger - exact_diff, 2)
            return order_price, trigger
    else:
        # Reverse order: ltp < trigger_price < order_price
        max_trigger = round(ltp + min_diff, 2)
        trigger = round(order_price - exact_diff, 2)
        if trigger > max_trigger:
            return order_price, trigger
        else:
            trigger = max_trigger
            order_price = round(trigger + exact_diff, 2)
            return order_price, trigger


def generate_gtt_plan(kite, scrip):
    symbol = scrip["symbol"]
    exchange = scrip["exchange"]
    entry1 = scrip.get("entry1")
    entry2 = scrip.get("entry2")
    entry3 = scrip.get("entry3")
    allocated = scrip["Allocated"]

    ltp = get_cmp(kite, symbol, exchange)
    if ltp is None:
        logging.error(f"Could not fetch CMP for {symbol}. Skipping.")
        return []

    # Determine how many valid entry levels are present
    valid_entries = [e for e in [entry1, entry2, entry3] if e is not None]
    num_valid = len(valid_entries)
    if num_valid == 0:
        logging.warning(f"No valid entry levels for {symbol}. Skipping.")
        return []

    qty = int(allocated / ltp)
    qty_splits = [qty // num_valid] * num_valid
    qty_splits[-1] += qty - sum(qty_splits)

    qty1 = qty_splits[0] if entry1 is not None else 0
    qty2 = qty_splits[1] if entry2 is not None and num_valid > 1 else 0
    qty3 = qty_splits[2] if entry3 is not None and num_valid > 2 else 0

    # Determine current holdings
    holdings = kite.holdings()
    total_qty = 0
    for holding in holdings:
        if holding["tradingsymbol"] == symbol:
            holding_qty = holding["quantity"]
            t1_qty = holding.get("t1_quantity", 0)
            total_qty = holding_qty + t1_qty
            break

    logging.debug(f"Total quantity for {symbol} (Holdings + T1): {total_qty}")

    plan = []

    # Entry level logic based on holding thresholds
    if total_qty == 0 and entry1 is not None:
        entry_price = entry1
        order_price = min(entry_price, round(ltp * LTP_ORDER_DIFF, 2)) if entry_price > ltp else entry_price
        order_price, trigger = trigger_price_and_adjust_order(order_price, ltp)
        plan.append({
            "symbol": symbol,
            "exchange": exchange,
            "price": order_price,
            "trigger": trigger,
            "qty": qty1,
            "ltp": round(ltp, 2),
            "entry": "E1"
        })

    elif total_qty <= qty // 3 and entry2 is not None:
        entry_price = entry2
        order_price = min(entry_price, round(ltp * LTP_ORDER_DIFF, 2)) if entry_price > ltp else entry_price
        order_price, trigger = trigger_price_and_adjust_order(order_price, ltp)
        plan.append({
            "symbol": symbol,
            "exchange": exchange,
            "price": order_price,
            "trigger": trigger,
            "qty": qty2,
            "ltp": round(ltp, 2),
            "entry": "E2"
        })

    elif total_qty <= (2 * qty) // 3 and entry3 is not None:
        entry_price = entry3
        order_price = min(entry_price, round(ltp * LTP_ORDER_DIFF, 2)) if entry_price > ltp else entry_price
        order_price, trigger = trigger_price_and_adjust_order(order_price, ltp)
        plan.append({
            "symbol": symbol,
            "exchange": exchange,
            "price": order_price,
            "trigger": trigger,
            "qty": qty3,
            "ltp": round(ltp, 2),
            "entry": "E3"
        })

    return plan




