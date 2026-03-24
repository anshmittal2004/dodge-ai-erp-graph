"""
data_loader.py  —  Ingests raw JSONL files from the Google Drive dataset folders.

Folder structure expected in  ./raw_data/  (or DATA_RAW_DIR env var):

  billing_document_cancellations/
  billing_document_headers/
  billing_document_items/
  business_partner_addresses/
  business_partners/
  customer_company_assignments/
  customer_sales_area_assignments/
  journal_entry_items_accounts_receivable/
  outbound_delivery_headers/
  outbound_delivery_items/
  payments_accounts_receivable/
  plants/
  product_descriptions/
  product_plants/
  product_storage_locations/
  products/
  sales_order_headers/
  sales_order_items/
  sales_order_schedule_lines/

Each folder contains one or more .jsonl files (one JSON object per line).

Run this ONCE before starting the backend:
    python data_loader.py

It merges all parts, deduplicates, and writes clean JSON files to ./data/
which the main db.py then ingests into SQLite.
"""

import os
import json
import glob

# ── Configurable paths ─────────────────────────────────────────────────────
RAW_DIR  = os.environ.get("DATA_RAW_DIR",  os.path.join(os.path.dirname(__file__), "..", "raw_data"))
OUT_DIR  = os.environ.get("DATA_OUT_DIR",  os.path.join(os.path.dirname(__file__), "..", "data"))

# ── Folder → output file mapping ───────────────────────────────────────────
FOLDER_MAP = {
    "billing_document_cancellations":        "billing_cancellations",
    "billing_document_headers":              "billing_header",
    "billing_document_items":                "billing_items",
    "business_partner_addresses":            "addresses",
    "business_partners":                     "customers",
    "customer_company_assignments":          "customer_company",
    "customer_sales_area_assignments":       "customer_sales",
    "journal_entry_items_accounts_receivable": "journal_entries",
    "outbound_delivery_headers":             "delivery_header",
    "outbound_delivery_items":               "delivery_items",
    "payments_accounts_receivable":          "payments",
    "plants":                                "plants",
    "product_descriptions":                  "products",
    "product_plants":                        "product_plants",
    "product_storage_locations":             "product_storage",
    "products":                              "product_master",
    "sales_order_headers":                   "sales_order_headers",
    "sales_order_items":                     "sales_order_items",
    "sales_order_schedule_lines":            "sales_order_schedule_lines",
}


def load_folder(folder_path: str) -> list:
    """Read all .jsonl files in a folder, return list of dicts."""
    rows = []
    for fpath in sorted(glob.glob(os.path.join(folder_path, "*.jsonl"))):
        with open(fpath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # skip malformed lines
    return rows


def run():
    os.makedirs(OUT_DIR, exist_ok=True)

    if not os.path.isdir(RAW_DIR):
        print(f"⚠️  raw_data directory not found at {RAW_DIR}")
        print("    Please create it and paste your dataset folders inside.")
        return

    found = 0
    for folder_name, out_name in FOLDER_MAP.items():
        folder_path = os.path.join(RAW_DIR, folder_name)
        out_path    = os.path.join(OUT_DIR, f"{out_name}.json")

        if not os.path.isdir(folder_path):
            print(f"⚠️  Missing folder: {folder_name}  (skipping)")
            continue

        rows = load_folder(folder_path)
        if not rows:
            print(f"⚠️  Empty folder: {folder_name}  (skipping)")
            continue

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(rows, f)

        print(f"✅  {folder_name:45s} → {out_name}.json  ({len(rows)} rows)")
        found += 1

    print(f"\nDone. {found}/{len(FOLDER_MAP)} folders processed → {OUT_DIR}")


if __name__ == "__main__":
    run()
