import logging
from token_manager import get_kite_session
from gtt_logic import generate_gtt_plan
from gtt_utils import sync_gtt_orders


import logging

logging.basicConfig(
    level=logging.INFO,  # or logging.WARNING to exclude debug messages
    format='%(levelname)s:%(name)s:%(message)s'
)


DRY_RUN = True  # Set to False to place real GTT orders

def read_csv(file_path):
    import csv
    entries = []
    with open(file_path, newline='') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            try:
                entries.append({
                    "symbol": row["symbol"],
                    "exchange": row["exchange"],
                    "entry1": float(row["entry1"]) if row["entry1"] else None,
                    "entry2": float(row["entry2"]) if row["entry2"] else None,
                    "entry3": float(row["entry3"]) if row["entry3"] else None,
                    "Allocated": float(row["Allocated"])
                })
            except Exception as e:
                logging.warning(f"Skipping row due to error: {e}")
    return entries

def main():
    logging.basicConfig(level=logging.INFO)
    kite = get_kite_session()
    input_file = "data/entry_levels.csv"
    scrips = read_csv(input_file)

    for scrip in scrips:
        gtt_plan = generate_gtt_plan(kite, scrip)
        logging.info(f"Generated GTT plan: {gtt_plan}")
        sync_gtt_orders(kite, gtt_plan, dry_run=DRY_RUN)

if __name__ == "__main__":
    main()
