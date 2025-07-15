import logging
import pandas as pd
from .token_manager import get_kite_session
from .gtt_logic import generate_gtt_plan, get_cmp, trigger_price_and_adjust_order
from .gtt_utils import sync_gtt_orders
import textwrap
from datetime import datetime
import os

logging.basicConfig(level=logging.INFO)

CSV_FILE_PATH = "data/entry_levels.csv"
DRY_RUN = False

def read_csv(file_path):
    try:
        return pd.read_csv(file_path).to_dict(orient="records")
    except Exception as e:
        logging.error(f"Failed to read CSV: {e}")
        return []

def print_wrapped_section(title, symbols, width=80):
    print(f"\n{title}")
    if symbols:
        wrapped = textwrap.fill(", ".join(symbols), width=width, subsequent_indent="  ")
        print(wrapped)
    else:
        print("  None")

def list_gtt_orders(kite, scrips):
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
            ltp = get_cmp(kite, symbol, exchange)
            if not ltp:
                continue
            
            total_qty = math.floor(allocated / ltp)
            held_qty = holdings_map.get(symbol, 0)

            if held_qty >= total_qty:
                fully_allocated_symbols.append(symbol)
                continue

            gtt_plan = generate_gtt_plan(kite, scrip)
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
            gtt_plan = generate_gtt_plan(kite, scrip)
            sync_gtt_orders(kite, gtt_plan, dry_run=DRY_RUN)


def analyze_gtt_orders(kite):
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
            ltp = get_cmp(kite, symbol, exchange)
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



def analyze_holdings(kite):
    
    update_tradebook(kite)

    try:
        import pandas as pd
        from datetime import datetime
        from .gtt_logic import get_cmp

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
                ltp = get_cmp(kite, symbol, holding.get("exchange", "NSE"))
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

            results.append({
                "Symbol": symbol,
                "Invested": invested,
                "P&L": pnl,
                "Yld/Day": yld_per_day,
                "ROI": roi,
                "Days Held (Age)": days_held,
                "P&L%": pnl_pct,
                "ROI/Day": roi_per_day
            })

        sorted_results = sorted(results, key=lambda x: x["ROI/Day"], reverse=True)

        print(f"{'Symbol':<15} {'Invested':>10} {'P&L':>10} {'Yld/Day':>10} {'Age':>5} {'P&L%':>8} {'ROI/Day':>10}")
        print("-" * 90)
        for r in sorted_results:
            print(f"{r['Symbol']:<15} {r['Invested']:>10.2f} {r['P&L']:>10.2f} {r['Yld/Day']:>10.2f} {r['Days Held (Age)']:>5} {r['P&L%']:>8.2f} {r['ROI/Day']:>10.2f}")

    except Exception as e:
        print(f"An error occurred while analyzing holdings: {e}")



def main():
    kite = get_kite_session()
    scrips = read_csv(CSV_FILE_PATH)

    while True:
        print("\nMenu:")
        print("1. List GTT orders")
        print("2. Analyze GTT orders")
        print("3. Analyze Holdings")
        print("4. Exit")
        choice = input("Enter your choice: ")

        if choice == "1":
            list_gtt_orders(kite, scrips)
        elif choice == "2":
            analyze_gtt_orders(kite)
        elif choice == "3":
            analyze_holdings(kite)
        elif choice == "4":
            print("Exiting...")
            break
        else:
            print("Invalid choice. Try again.")

if __name__ == "__main__":
    main()
