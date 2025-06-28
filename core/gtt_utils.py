import logging

def sync_gtt_orders(kite, gtt_plan, dry_run=False):
    existing_orders = kite.get_gtts()

    for order in gtt_plan:
        symbol = order["symbol"]
        existing = [
            g for g in existing_orders
            if g["condition"]["tradingsymbol"] == symbol and
               g["orders"][0]["transaction_type"] == kite.TRANSACTION_TYPE_BUY
        ]

        if existing:
            logging.info(f"[INFO] Skipping {symbol}, GTT already exists")
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
