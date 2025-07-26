import time
import logging
import requests
from .token_manager import get_valid_upstox_access_token
from .gtt_logic import get_instrument_key_from_csv

class CMPManager:
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.cache = {}
        self.last_updated = 0
        self.ttl = 600  # 10 minutes

    def _is_cache_valid(self):
        return (time.time() - self.last_updated) < self.ttl

    def _collect_symbols(self, holdings, gtts, entry_levels):
        symbols = set()
        for h in holdings:
            symbols.add((h["exchange"], h["tradingsymbol"].replace("#", "")))
        for g in gtts:
            if g["orders"][0]["transaction_type"] == "BUY":
                symbols.add((g["condition"]["exchange"], g["condition"]["tradingsymbol"]))
        for s in entry_levels:
            symbols.add((s["exchange"], s["symbol"]))
        logging.debug(f"Collected symbols for CMP fetch: {symbols}")

        return list(symbols)

    def _fetch_bulk_quote_upstox(self, symbols):
        def fetch_quotes(token, instrument_keys):
            headers = {
                "Accept": "application/json",
                "Authorization": f"Bearer {token}"
            }
            params = {"instrument_key": ",".join(instrument_keys)}
            url = "https://api.upstox.com/v2/market-quote/quotes"
            return requests.get(url, headers=headers, params=params)

        from .token_manager import get_valid_upstox_access_token, generate_new_upstox_token
        token = get_valid_upstox_access_token()
        instrument_keys = []
        symbol_map = {}

        for exch, sym in symbols:
            segment = exch + "_EQ"
            instrument_key = get_instrument_key_from_csv(sym, self.csv_path, segment)
            if instrument_key:
                instrument_keys.append(instrument_key)
                normalized_key = f"{segment}:{sym}"
                symbol_map[normalized_key] = (exch, sym)
                logging.debug(f"Mapped {normalized_key} -> ({exch}, {sym})")
            else:
                logging.warning(f"Instrument key not found for {sym} in segment {segment}")

        if not instrument_keys:
            logging.warning("No instrument keys found. Skipping quote fetch.")
            return {}

        quote_map = {}
        batch_size = 50

        for i in range(0, len(instrument_keys), batch_size):
            batch_keys = instrument_keys[i:i + batch_size]
            response = fetch_quotes(token, batch_keys)

            if response.status_code == 401:
                try:
                    error_data = response.json()
                    error_code = error_data.get("errors", [{}])[0].get("errorCode")
                    if error_code == "UDAPI100050":
                        logging.info("Invalid Upstox token detected. Regenerating token...")
                        token = generate_new_upstox_token()
                        response = fetch_quotes(token, batch_keys)
                except Exception as e:
                    logging.error(f"Error while handling token regeneration: {e}")
                    continue

            if response.status_code != 200:
                logging.error(f"Failed to fetch batch quote: {response.status_code}")
                continue

            data = response.json().get("data", {})
            for key, quote in data.items():
                exch, sym = symbol_map.get(key, (None, None))
                if exch and sym:
                    quote_map[(exch, sym)] = quote
                    logging.debug(f"✅ Added to cache: {sym} ({exch}) -> CMP: {quote.get('last_price')}")

        logging.info(f"Fetched quotes for {len(quote_map)} symbols")
        return quote_map

    
    def refresh_cache(self, holdings, gtts, entry_levels):
        symbols = self._collect_symbols(holdings, gtts, entry_levels)
        self.cache = self._fetch_bulk_quote_upstox(symbols)
        self.last_updated = time.time()
        logging.info(f"CMP cache refreshed with {len(self.cache)} symbols.")

    def get_quote(self, exchange, symbol):
        if not self._is_cache_valid():
            raise RuntimeError("CMP cache is stale. Please refresh it first.")
        return self.cache.get((exchange, symbol))
    
    def get_cmp(self, exchange, symbol):
        quote = self.cache.get((exchange, symbol))
        if quote:
            return quote.get("last_price")
        return None

   
    def print_all_cmps(self):
        print("\n📊 Cached CMPs:")
        print(f"{'Symbol':<15} {'Exchange':<10} {'CMP':<10}")
        print("-" * 40)
        for (exchange, symbol), quote in self.cache.items():
            cmp = quote.get("last_price", "N/A")
            print(f"{symbol:<15} {exchange:<10} {cmp:<10}")
