import webbrowser
import requests
import pandas as pd
from urllib.parse import urlparse, parse_qs

# ============ CONFIGURATION ============
API_KEY = "8ea96b17-be6c-42cd-b921-a1ad97b45bd0"
API_SECRET = "n4pb284a6g"
REDIRECT_URI = "http://localhost"
CSV_PATH = "data/Name-symbol-mapping.csv"
EXCHANGE_SEGMENT = "BSE_EQ"  # Use NSE_EQ for most stocks
SYMBOL = "539997"  # Enter the symbol you want CMP for
# =======================================

def get_instrument_key_from_csv(symbol: str, csv_path: str, exchange_segment: str = "NSE_EQ") -> str:
    try:
        df = pd.read_csv(csv_path)
        df.columns = [col.strip() for col in df.columns]
        match = df[df['SYMBOL'].str.upper() == symbol.upper()]
        if not match.empty:
            isin = match.iloc[0]['ISIN NUMBER'].strip()
            return f"{exchange_segment}|{isin}"
        else:
            print(f"❌ Symbol '{symbol}' not found in the CSV.")
            return None
    except Exception as e:
        print(f"❌ Error reading CSV or extracting instrument key: {e}")
        return None

# Step 1: Get instrument key
instrument_key = get_instrument_key_from_csv(SYMBOL, CSV_PATH, EXCHANGE_SEGMENT)
if not instrument_key:
    exit(1)
print(f"🔑 Instrument Key for {SYMBOL}: {instrument_key}")

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

UPSTOX_TOKEN_FILE = "auth/upstox_access_token.pkl"

import pickle 
import os 

def load_token(token_file: str) -> str | None:
    if os.path.exists(token_file):
        with open(token_file, "rb") as f:
            return pickle.load(f)
    return None

def get_valid_upstox_access_token() -> str:
    access_token = load_token(UPSTOX_TOKEN_FILE)
    if access_token:
        return access_token

access_token = load_token(UPSTOX_TOKEN_FILE)
# Step 5: Fetch CMP (LTP) using instrument key
ltp_url = f"https://api.upstox.com/v2/market-quote/ltp?instrument_key={instrument_key}"
headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {access_token}"
}

ltp_response = requests.get(ltp_url, headers=headers)
ltp_data = ltp_response.json()


try:
    # Get the first (and likely only) key from the data dictionary
    actual_key = list(ltp_data["data"].keys())[0]
    cmp = ltp_data["data"][actual_key]["last_price"]
    print(f"\n📈 CMP for {SYMBOL} ({actual_key}): ₹{cmp}")
    
except Exception as e:
    print(f"\n❌ Could not extract CMP. Full response: {e}")
    print(ltp_data)


from kiteconnect import KiteConnect

# Initialize KiteConnect with your API key
kite = KiteConnect(api_key="your_api_key")

# Generate session using request token and your API secret
data = kite.generate_session("your_request_token", api_secret="your_api_secret")
kite.set_access_token(data["access_token"])

# Fetch trade history
trades = kite.trades()

# Filter trades for a specific symbol
symbol = "RELIANCE"
symbol_trades = [trade for trade in trades if trade['tradingsymbol'] == symbol]

# Print trade history for the symbol
for trade in symbol_trades:
    print(trade)

