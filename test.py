import requests

# Replace with your actual Alpha Vantage API key
API_KEY = "0W581T133UG8RLJ9"

# BSE or NSE symbol (use 'BSE:RELIANCE' or 'RELIANCE.BSE')
symbol = "RELIANCE.BSE"  # Or "TCS.NSE", if supported

# Alpha Vantage endpoint
url = "https://www.alphavantage.co/query"

params = {
    "function": "GLOBAL_QUOTE",
    "symbol": symbol,
    "apikey": API_KEY
}

try:
    response = requests.get(url, params=params)
    data = response.json()

    if "Global Quote" in data and data["Global Quote"]:
        cmp = data["Global Quote"]["05. price"]
        print(f"Current Market Price of {symbol}: ₹{cmp}")
    else:
        print(f"No data found for {symbol} or API limit exceeded.")
except Exception as e:
    print("Error fetching CMP:", e)
