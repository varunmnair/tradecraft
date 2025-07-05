import logging

from datetime import datetime
import logging

def sync_gtt_orders(kite, gtt_plan, dry_run=False):
    # Fetch all GTTs
    all_gtts = kite.get_gtts()

    # Filter out GTTs that are triggered and not triggered today
    today = datetime.today().date()
    existing_orders = []
    for g in all_gtts:
        if g["orders"][0]["transaction_type"] != kite.TRANSACTION_TYPE_BUY:
            continue
        if g["status"] == "triggered":
            triggered_at = g.get("triggered_at")
            if triggered_at:
                try:
                    triggered_date = datetime.strptime(triggered_at[:10], "%Y-%m-%d").date()
                    if triggered_date != today:
                        continue
                except Exception as e:
                    logging.warning(f"Could not parse triggered_at for GTT {g['id']}: {e}")
                    continue
        existing_orders.append(g)

    for order in gtt_plan:
        symbol = order["symbol"]
        existing = [
            g for g in existing_orders
            if g["condition"]["tradingsymbol"] == symbol and
               g["orders"][0]["transaction_type"] == kite.TRANSACTION_TYPE_BUY
        ]

        if existing:
            logging.debug(f"[INFO] Skipping {symbol}, GTT already exists")
        else:
            logging.info(f"[INFO] ✅ Placing new GTT for {symbol} @ {order['price']}")
            if not dry_run:
                try:
                    kite.place_gtt(
                        trigger_type=kite.GTT_TYPE_SINGLE,
                        tradingsymbol=symbol,
                        exchange=order["exchange"],
                        trigger_values=[order["trigger"]],
                        last_price=order["ltp"],
                        orders=[{
                            "transaction_type": kite.TRANSACTION_TYPE_BUY,
                            "quantity": order["qty"],
                            "order_type": kite.ORDER_TYPE_LIMIT,
                            "product": kite.PRODUCT_CNC,
                            "price": order["price"]
                        }]
                    )
                except Exception as e:
                    logging.error(f"[ERROR] ❌ Failed to place GTT for {symbol}: {e}")
