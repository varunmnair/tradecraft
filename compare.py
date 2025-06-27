import logging
import pandas as pd
from token_manager import get_kite_session
from gtt_logic import generate_gtt_plan
from gtt_utils import sync_gtt_orders

logging.basicConfig(level=logging.INFO)

CSV_FILE_PATH = "data/entry_levels.csv"
DRY_RUN = True

def read_csv(file_path):
    try:
        return pd.read_csv(file_path).to_dict(orient="records")
    except Exception as e:
        logging.error(f"Failed to read CSV: {e}")
        return []

def list_gtt_orders(kite, scrips):
    import math
    from gtt_logic import get_cmp  # Ensure this is imported if not already

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
            h["tradingsymbol"]: h["quantity"] + h.get("t1_quantity", 0)
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
        print(f"Order Exists. Orders will be skipped for symbols: {', '.join(existing_orders)}")

    if fully_allocated_symbols:
        print(f"All entry levels completed. Orders will be skipped for symbols: {', '.join(fully_allocated_symbols)}")

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

    if input("1.1 Place GTT orders? (y/n): ").lower() == "y":
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
            ltp = g["condition"]["last_price"]
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
                        from gtt_logic import trigger_price_and_adjust_order
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


def main():
    kite = get_kite_session()
    scrips = read_csv(CSV_FILE_PATH)

    while True:
        print("\nMenu:")
        print("1. List GTT orders")
        print("2. Analyze GTT orders")
        print("3. Exit")
        choice = input("Enter your choice: ")

        if choice == "1":
            list_gtt_orders(kite, scrips)
        elif choice == "2":
            analyze_gtt_orders(kite)
        elif choice == "3":
            print("Exiting...")
            break
        else:
            print("Invalid choice. Try again.")

if __name__ == "__main__":
    main()
