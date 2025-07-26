import logging
import pandas as pd
from .token_manager import get_kite_session
from .gtt_logic import generate_gtt_plan,  trigger_price_and_adjust_order
from .gtt_utils import sync_gtt_orders
import textwrap
from datetime import datetime
import os
from collections import Counter
from .cmp_cache import CMPManager


logging.basicConfig(level=logging.INFO)

CSV_FILE_PATH = "data/entry_levels.csv"
DRY_RUN = False

def read_csv(file_path):
    try:
        return pd.read_csv(file_path).to_dict(orient="records")
    except Exception as e:
        logging.error(f"Failed to read CSV: {e}")
        return []


def detect_duplicate_symbols(scrips):
    symbol_counts = Counter(s['symbol'] for s in scrips)
    duplicates = [symbol for symbol, count in symbol_counts.items() if count > 1]
    if duplicates:
        print("\n⚠️ Duplicate entries found in entry_levels.csv for the following symbols:")
        for symbol in duplicates:
            print(f"  - {symbol}")
    else:
        print("\n✅ No duplicate entries found in entry_levels.csv.")


def print_wrapped_section(title, symbols, width=80):
    print(f"\n{title}")
    if symbols:
        wrapped = textwrap.fill(", ".join(symbols), width=width, subsequent_indent="  ")
        print(wrapped)
    else:
        print("  None")

def list_gtt_orders(kite, scrips, cmp_manager):
    import math
    
    existing_orders = []
    new_orders = []
    fully_allocated_symbols = []

    # Fetch existing GTT orders from Zerodha
    try:
        gtts = kite.get_gtts()
        existing_symbols = [
            g["condition"]["tradingsymbol"]
            for g in gtts
            if g["orders"][0]["transaction_type"] == kite.TRANSACTION_TYPE_BUY
        ]
    except Exception as e:
        logging.error(f"Error fetching existing GTTs: {e}")
        existing_symbols = []

    # Fetch current holdings
    try:
        holdings = kite.holdings()
        holdings_map = {
        h["tradingsymbol"].replace("#", ""): h["quantity"] + h.get("t1_quantity", 0)
        for h in holdings
        }

    except Exception as e:
        logging.error(f"Error fetching holdings: {e}")
        holdings_map = {}

    for scrip in scrips:
        symbol = scrip["symbol"]
        exchange = scrip["exchange"]
        allocated = scrip["Allocated"]

        try:
            ltp = cmp_manager.get_cmp(exchange, symbol)
            if not ltp:
                continue
            
            total_qty = math.floor(allocated / ltp)
            held_qty = holdings_map.get(symbol, 0)

            if held_qty >= total_qty:
                fully_allocated_symbols.append(symbol)
                continue

            gtt_plan = gtt_plan = generate_gtt_plan(kite, scrip, cmp_manager)

            if symbol in existing_symbols:
                existing_orders.append(symbol)
            else:
                new_orders.extend(gtt_plan)

        except Exception as e:
            logging.warning(f"Skipping {symbol} due to error: {e}")
            continue

    if existing_orders:
        print_wrapped_section("📌 Order Exists - Skipping GTT placement for:", existing_orders)

    if fully_allocated_symbols:
        print_wrapped_section("📌 All Entry Levels Completed - Skipping GTT placement for:", fully_allocated_symbols)


    if new_orders:
        print(f"\n{'Symbol':<15} {'Order Price':<15} {'Trigger Price':<15} {'LTP':<15} {'Order Amount':<15} {'Entry Level':<15}")
        for order in new_orders:
            symbol = order["symbol"]
            price = order["price"]
            trigger = order["trigger"]
            ltp = order["ltp"]
            qty = order["qty"]
            entry = order.get("entry", "-")
            amount = round(price * qty, 2)
            print(f"{symbol:<15} {price:<15} {trigger:<15} {ltp:<15} {amount:<15} {entry:<15}")

    if input("\n1.1 Place GTT orders? (y/n): ").lower() == "y":
        for scrip in scrips:
            gtt_plan = gtt_plan = generate_gtt_plan(kite, scrip, cmp_manager)
            sync_gtt_orders(kite, gtt_plan, dry_run=DRY_RUN)


def analyze_gtt_orders(kite, cmp_manager):
    try:
        gtts = kite.get_gtts()
        orders = []
        symbol_count = {}
        total_amount = 0.0
        gtt_map = {}

        for g in gtts:
            if g["orders"][0]["transaction_type"] != kite.TRANSACTION_TYPE_BUY:
                continue

            symbol = g["condition"]["tradingsymbol"]
            trigger = g["condition"]["trigger_values"][0]
            exchange = g["condition"]["exchange"]
            ltp = cmp_manager.get_cmp(exchange, symbol)
            qty = g["orders"][0]["quantity"]
            price = g["orders"][0]["price"]
            gtt_id = g["id"]
            exchange = g["condition"]["exchange"]
            variance = round(((ltp - trigger) / trigger) * 100, 2)

            orders.append({
                "Symbol": symbol,
                "Trigger Price": trigger,
                "LTP": ltp,
                "Variance (%)": variance,
                "Qty": qty,
                "Price": price,
                "GTT ID": gtt_id,
                "Exchange": exchange
            })

            symbol_count[symbol] = symbol_count.get(symbol, 0) + 1
            total_amount += price * qty
            gtt_map[gtt_id] = g

        sorted_orders = sorted(orders, key=lambda x: x["Variance (%)"])

        if not sorted_orders:
            print("No BUY-type GTT orders found.")
            return

        print(f"\n{'Symbol':<15} {'Trigger Price':<15} {'LTP':<15} {'Variance (%)':<15}")
        for order in sorted_orders:
            print(f"{order['Symbol']:<15} {order['Trigger Price']:<15} {order['LTP']:<15} {order['Variance (%)']:<15}")

        duplicates = [symbol for symbol, count in symbol_count.items() if count > 1]
        if duplicates:
            print(f"\nDuplicate GTT orders found for symbols: {', '.join(duplicates)}")

        print(f"\nTotal capital required to execute all GTT orders: ₹{round(total_amount, 2)}")

        # Sub-options
        print("\nSub-options:")
        print("1. Delete GTTs with variance greater than a threshold")
        print("2. Adjust GTTs to match a target variance")
        sub_choice = input("Enter your sub-option (1/2 or press Enter to skip): ").strip()

        if sub_choice == "1":
            threshold = float(input("Enter variance threshold (e.g., 5 for 5%): "))
            for order in orders:
                if order["Variance (%)"] > threshold:
                    try:
                        kite.delete_gtt(order["GTT ID"])
                        print(f"Deleted GTT for {order['Symbol']} with variance {order['Variance (%)']}%")
                    except Exception as e:
                        print(f"Failed to delete GTT for {order['Symbol']}: {e}")

        elif sub_choice == "2":
            target_variance = float(input("Enter target variance (e.g., -3 for -3%): "))
            for order in orders:
                if order["Variance (%)"] < target_variance:
                    try:
                        new_trigger = round(order["LTP"] / (1 + target_variance / 100), 2)
                        
                        new_price, new_trigger = trigger_price_and_adjust_order(order_price=new_trigger, ltp=order["LTP"])

                        kite.delete_gtt(order["GTT ID"])
                        kite.place_gtt(
                            trigger_type=kite.GTT_TYPE_SINGLE,
                            tradingsymbol=order["Symbol"],
                            exchange=order["Exchange"],
                            trigger_values=[new_trigger],
                            last_price=order["LTP"],
                            orders=[{
                                "transaction_type": kite.TRANSACTION_TYPE_BUY,
                                "quantity": order["Qty"],
                                "order_type": kite.ORDER_TYPE_LIMIT,
                                "product": kite.PRODUCT_CNC,
                                "price": new_price
                            }]
                        )
                        print(f"Modified GTT for {order['Symbol']} to match variance {target_variance}%")
                    except Exception as e:
                        print(f"Failed to modify GTT for {order['Symbol']}: {e}")

    except Exception as e:
        logging.error(f"Error analyzing GTTs: {e}")



def update_tradebook(kite, tradebook_path="data/zerodha-tradebook-master.csv"):
    # Fetch trades from Kite
    new_trades = kite.trades()

    # Convert new trades to DataFrame
    new_trades_df = pd.DataFrame(new_trades)

    if new_trades_df.empty:
        print("No new trades found.")
        return

    # Normalize and rename columns to match tradebook format
    new_trades_df = new_trades_df.rename(columns={
        "tradingsymbol": "symbol",
        "exchange": "exchange",
        "instrument_token": "isin",  # Placeholder, actual ISIN may not be available
        "transaction_type": "trade_type",
        "quantity": "quantity",
        "average_price": "price",
        "trade_id": "trade_id",
        "order_id": "order_id",
        "exchange_timestamp": "order_execution_time"
    })

    new_trades_df["isin"] = ""  # ISIN not available from kite.trades()
    new_trades_df["segment"] = "EQ"
    new_trades_df["series"] = new_trades_df["symbol"].apply(lambda x: "EQ")
    new_trades_df["auction"] = False
    new_trades_df["trade_date"] = pd.to_datetime(new_trades_df["order_execution_time"]).dt.date
    new_trades_df["trade_date"] = new_trades_df["trade_date"].apply(lambda x: x.strftime("%#m/%#d/%Y"))


    # Reorder columns to match the tradebook format
    new_trades_df = new_trades_df[[
        "symbol", "isin", "trade_date", "exchange", "segment", "series",
        "trade_type", "auction", "quantity", "price", "trade_id", "order_id", "order_execution_time"
    ]]

    # Load existing tradebook if it exists
    if os.path.exists(tradebook_path):
        existing_df = pd.read_csv(tradebook_path)
        existing_trade_ids = set(existing_df["trade_id"].astype(str))
    else:
        existing_df = pd.DataFrame(columns=new_trades_df.columns)
        existing_trade_ids = set()

    # Filter out trades that already exist
    new_trades_df = new_trades_df[~new_trades_df["trade_id"].astype(str).isin(existing_trade_ids)]

    if not new_trades_df.empty:
        updated_df = pd.concat([existing_df, new_trades_df], ignore_index=True)
        updated_df.to_csv(tradebook_path, index=False)
        print(f"Appended {len(new_trades_df)} new trades to the tradebook.")
    else:
        print("No new trades to append.")


def write_roi_results(results, output_path="data/roi-master.csv"):
    # Ensure the output directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Get today's date and check if it's Saturday or Sunday
    today = datetime.today()
    if today.weekday() in (5, 6):  # 5 = Saturday, 6 = Sunday
        print("\nToday is Saturday or Sunday. Skipping write to ROI master.")
        return

    today_str = today.strftime("%Y-%m-%d")

    # Create a DataFrame from the results
    df_new = pd.DataFrame(results)
    df_new["Date"] = today_str

    # Rename columns to match the required output format
    df_new = df_new.rename(columns={
        "Symbol": "Symbol",
        "Invested": "Invested Amount",
        "P&L": "Absolute Profit",
        "Yld/Day": "Yield Per Day",
        "Days Held (Age)": "Age of Stock",
        "P&L%": "Profit Percentage",
        "ROI/Day": "ROI per day"
    })

    # Reorder columns
    df_new = df_new[[
        "Date", "Symbol", "Invested Amount", "Absolute Profit",
        "Yield Per Day", "Age of Stock", "Profit Percentage", "ROI per day"
    ]]

    # Load existing file if it exists
    if os.path.exists(output_path):
        df_existing = pd.read_csv(output_path)
    else:
        df_existing = pd.DataFrame(columns=df_new.columns)

    # Combine and drop duplicates based on Date and Symbol
    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    df_combined.drop_duplicates(subset=["Date", "Symbol"], keep="last", inplace=True)

    # Save the updated file
    df_combined.to_csv(output_path, index=False)

    print(f"ROI results written to {output_path}")


def analyze_holdings(kite, cmp_manager):
    
    update_tradebook(kite)

    try:
        import pandas as pd
        from datetime import datetime


        tradebook_path = "data/zerodha-tradebook-master.csv"
        trades_df = pd.read_csv(tradebook_path)
        trades_df.columns = [col.strip().lower().replace(" ", "_") for col in trades_df.columns]
        trades_df["trade_date"] = pd.to_datetime(trades_df["trade_date"], errors='coerce')
        trades_df = trades_df[trades_df["trade_type"].str.lower() == "buy"]

        holdings = kite.holdings()
        results = []


        for holding in holdings:
            symbol = holding["tradingsymbol"]
            symbol_clean = symbol.replace("#", "").upper()
            quantity = holding["quantity"] + holding.get("t1_quantity", 0)
            avg_price = holding["average_price"]
            invested = quantity * avg_price

            ltp = holding["last_price"]
            if not ltp:
                ltp = cmp_manager.get_cmp(holding.get("exchange", "NSE"), symbol)
            if not ltp:
                continue

            current_value = quantity * ltp
            pnl = current_value - invested
            pnl_pct = (pnl / invested * 100) if invested else 0
            roi = pnl_pct

            symbol_trades = trades_df[trades_df["symbol"].str.upper() == symbol_clean]
            symbol_trades = symbol_trades.sort_values(by="trade_date", ascending=False)

            qty_needed = quantity
            weighted_sum = 0
            total_qty = 0

            for _, trade in symbol_trades.iterrows():
                if qty_needed <= 0:
                    break
                trade_qty = trade["quantity"]
                trade_date = trade["trade_date"].date()
                used_qty = min(qty_needed, trade_qty)
                weighted_sum += used_qty * trade_date.toordinal()
                total_qty += used_qty
                qty_needed -= used_qty

            if total_qty > 0:
                avg_date_ordinal = weighted_sum / total_qty
                avg_date = datetime.fromordinal(int(avg_date_ordinal)).date()
                days_held = (datetime.today().date() - avg_date).days
            else:
                days_held = 0

            yld_per_day = (pnl / days_held) if days_held > 0 else 0
            roi_per_day = (roi / days_held) if days_held > 0 else 0

            # Get trend for this symbol
            trend_result = analyze_symbol_trend(symbol)
            if trend_result:
                trend_str = f"{trend_result[0]}({trend_result[1]})"
            else:
                trend_str = "-"

            results.append({
                "Symbol": symbol,
                "Invested": invested,
                "P&L": pnl,
                "Yld/Day": yld_per_day,
                "ROI": roi,
                "Days Held (Age)": days_held,
                "P&L%": pnl_pct,
                "ROI/Day": roi_per_day,
                "Trend": trend_str
            })


        sorted_results = sorted(results, key=lambda x: x["ROI/Day"], reverse=True)

        print(f"{'Symbol':<15} {'Invested':>10} {'P&L':>10} {'Yld/Day':>10} {'Age':>5} {'P&L%':>8} {'ROI/Day':>10} {'Trend':>10}")
        print("-" * 105)
        for r in sorted_results:
            print(f"{r['Symbol']:<15} {r['Invested']:>10.2f} {r['P&L']:>10.2f} {r['Yld/Day']:>10.2f} {r['Days Held (Age)']:>5} {r['P&L%']:>8.2f} {r['ROI/Day']:>10.2f} {r['Trend']:>10}")

    except Exception as e:
        print(f"An error occurred while analyzing holdings: {e}")


    write_roi_results(results)

    # Show trend of average ROI per day for the latest 5 dates
    try:
        roi_path = "data/roi-master.csv"
        if os.path.exists(roi_path):
            df = pd.read_csv(roi_path)
            df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
            # Only consider symbols in current holdings
            holding_symbols = set(h["tradingsymbol"].replace("#", "").upper() for h in holdings)
            df = df[df["Symbol"].str.upper().isin(holding_symbols)]
            # Group by date, get average ROI per day
            grouped = df.groupby("Date")["ROI per day"].mean().sort_index(ascending=False)
            latest_5 = grouped.head(5)[::-1]  # reverse to chronological order
            trend_str = " -> ".join(f"{v:.4f}" for v in latest_5)
            print(f"\nAverage ROI/Day trend (latest 5 dates): {trend_str}")
    except Exception as e:
        print(f"Error showing average ROI/Day trend: {e}")

def analyze_roi_trend(file_path="data/roi-master.csv", N=3):
    try:
        df = pd.read_csv(file_path)
        df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
        df.sort_values(by=["Symbol", "Date"], inplace=True)

        N = int(input("Enter the number of consecutive days for uptrend (N): "))

        direction = input("Choose trend direction:\n1. View upward trend\n2. View downward trend\nEnter 1 or 2: ").strip()
        if direction not in {"1", "2"}:
            print("Invalid choice. Please enter 1 or 2.")
            return

        # Get current holdings symbols
        try:
            from .token_manager import get_kite_session
            kite = get_kite_session()
            holdings = kite.holdings()
            holding_symbols = set(h["tradingsymbol"].replace("#", "").upper() for h in holdings)
        except Exception as e:
            print(f"Error fetching holdings for ROI filter: {e}")
            holding_symbols = set()

        results = []

        for symbol, group in df.groupby("Symbol"):
            if symbol.upper() not in holding_symbols:
                continue
            # Sort by ascending date (oldest to latest)
            group = group.sort_values("Date", ascending=True)
            roi_series = group["ROI per day"].values[-N:]  # last N days, oldest to latest

            if len(roi_series) < N:
                continue

            window = roi_series  # oldest to latest

            if direction == "1" and all(x < y for x, y in zip(window, window[1:])):
                change = window[-1] - window[0]
                trend_str = " -> ".join(f"{roi:.3f}" for roi in window)
                results.append({
                    "Symbol": symbol,
                    "Change": change,
                    "Trend": trend_str
                })
            elif direction == "2" and all(x > y for x, y in zip(window, window[1:])):
                change = window[0] - window[-1]
                trend_str = " -> ".join(f"{roi:.3f}" for roi in window)
                results.append({
                    "Symbol": symbol,
                    "Change": change,
                    "Trend": trend_str
                })

        sorted_results = sorted(results, key=lambda x: x["Change"], reverse=True)

        print(f"\n{'Symbol':<15} {'Change':>10} {'Trend':>30}")
        print("-" * 60)
        for r in sorted_results:
            print(f"{r['Symbol']:<15} {r['Change']:>10.4f} {r['Trend']:>30}")

    except Exception as e:
        print(f"Error analyzing ROI trend: {e}")


import pandas as pd

def analyze_symbol_trend(symbol, file_path="data/roi-master.csv", threshold=0.002):
    """
    Analyze the trend (uptrend or downtrend) for a given symbol in roi-master.csv.
    Returns ("UP", n) or ("DOWN", n) where n is the number of days the trend has continued.
    Small fluctuations within the threshold are ignored.
    """
    try:
        df = pd.read_csv(file_path)
        df = df[df["Symbol"].str.upper() == symbol.upper()]
        if df.empty or len(df) < 2:
            return None

        df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
        df = df.sort_values("Date", ascending=True)
        roi_series = df["ROI per day"].values

        trend = None
        count = 1

        for i in range(len(roi_series) - 1, 0, -1):
            today = roi_series[i]
            prev = roi_series[i - 1]
            diff = today - prev

            if trend is None:
                if abs(diff) <= threshold:
                    return "FLAT",1
                trend = "UP" if diff > 0 else "DOWN"
                count = 1
            else:
                if trend == "UP" and diff > threshold:
                    count += 1
                elif trend == "DOWN" and diff < -threshold:
                    count += 1
                else:
                    break

        return trend, count

    except Exception as e:
        print(f"Error analyzing symbol trend: {e}")
        return None



def main():
    kite = get_kite_session()
    scrips = read_csv(CSV_FILE_PATH)

    try:
        holdings = kite.holdings()
    except Exception as e:
        logging.error(f"Error fetching holdings: {e}")
        holdings = []

    try:
        gtts = kite.get_gtts()
    except Exception as e:
        logging.error(f"Error fetching GTTs: {e}")
        gtts = []

    # Initialize CMPManager and refresh cache
    cmp_manager = CMPManager(csv_path="data/Name-symbol-mapping.csv")
    cmp_manager.refresh_cache(holdings, gtts, scrips)
    #cmp_manager.print_all_cmps()

    while True:
        print("\nMenu:")
        print("1. List GTT orders")
        print("2. Analyze GTT orders")
        print("3. Analyze Holdings")
        print("4. Analyze ROI")
        print("5. Exit")
        choice = input("Enter your choice: ")

        if choice == "1":
            detect_duplicate_symbols(scrips)
            list_gtt_orders(kite, scrips, cmp_manager)
        elif choice == "2":
            analyze_gtt_orders(kite, cmp_manager)
        elif choice == "3":
            analyze_holdings(kite, cmp_manager)
        elif choice == "4":
            analyze_roi_trend()
        elif choice == "5":
            print("Exiting...")
            break
        else:
            print("Invalid choice. Please try again.")


if __name__ == "__main__":
    main()
