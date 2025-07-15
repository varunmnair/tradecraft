from token_manager import get_kite_session



def main():
    kite = get_kite_session()
    orders = kite.orders()
    symbol = "HGIINFRA"
    past_orders = [order for order in orders if order['tradingsymbol'] == symbol and order['status'] == 'COMPLETE']

    for order in past_orders:
        print(f"Order ID: {order['order_id']}, Qty: {order['quantity']}, Price: ₹{order['average_price']}, Date: {order['order_timestamp']}")

    trades = kite.trades()

    print(trades)


main()