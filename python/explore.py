import pandas as pd
import ast
import os

# ── Config ────────────────────────────────────────────────────
BASE = os.path.expanduser("~/Downloads/Furniture_retail")

REES46_FILE     = os.path.join(BASE, "2019-Nov.csv")
SUPERSTORE_FILE = os.path.join(BASE, "superstore.csv")

# ══════════════════════════════════════════════════════════════
# HELPER
# ══════════════════════════════════════════════════════════════
def section(title):
    print("\n" + "═" * 60)
    print(f"  {title}")
    print("═" * 60)

# ══════════════════════════════════════════════════════════════
# 1. AMAZON FURNITURE PRODUCTS (superstore.csv)
# ══════════════════════════════════════════════════════════════
section("LOADING Amazon Furniture Products (superstore.csv)...")
prod = pd.read_csv(SUPERSTORE_FILE, encoding="latin1")

section("PRODUCT CATALOG — Basic Info")
print(f"  Rows          : {len(prod):,}")
print(f"  Columns       : {prod.shape[1]}")
print(f"\n  Column names  : {list(prod.columns)}")

section("PRODUCT CATALOG — Null counts per column")
for col in prod.columns:
    nulls = prod[col].isnull().sum()
    pct   = nulls / len(prod) * 100
    if nulls > 0:
        print(f"  {col:<30} {nulls:>4} nulls  ({pct:.1f}%)")

section("PRODUCT CATALOG — Price column")
prod["price_clean"] = (
    prod["price"]
    .astype(str)
    .str.replace("$", "", regex=False)
    .str.replace(",", "", regex=False)
    .str.strip()
)
prod["price_clean"] = pd.to_numeric(prod["price_clean"], errors="coerce")
print(f"  Raw nulls          : {prod['price'].isnull().sum()}")
print(f"  After cleaning     : {prod['price_clean'].isnull().sum()} nulls")
print(f"\n  Price stats:")
print(prod["price_clean"].describe().to_string())

section("PRODUCT CATALOG — Category parsing")
def extract_main_category(cat_str):
    try:
        cats = ast.literal_eval(str(cat_str))
        return cats[1] if len(cats) > 1 else cats[0]
    except:
        return None

def extract_sub_category(cat_str):
    try:
        cats = ast.literal_eval(str(cat_str))
        return cats[2] if len(cats) > 2 else None
    except:
        return None

prod["main_category"] = prod["categories"].apply(extract_main_category)
prod["sub_category"]  = prod["categories"].apply(extract_sub_category)

print("  Main category breakdown:")
print(prod["main_category"].value_counts().head(10).to_string())
print("\n  Sub-category breakdown:")
print(prod["sub_category"].value_counts().head(15).to_string())

section("PRODUCT CATALOG — Brand & other fields")
print(f"  Unique brands      : {prod['brand'].nunique()}")
print(f"  Top 10 brands:")
print(prod["brand"].value_counts().head(10).to_string())
print(f"\n  Availability values:")
print(prod["availability"].value_counts().head(8).to_string())
print(f"\n  Materials:")
print(prod["material"].value_counts().head(10).to_string())

out_prod = os.path.join(BASE, "products_clean_preview.csv")
prod[["asin","title","brand","price_clean","main_category",
      "sub_category","availability","material","color",
      "style","country_of_origin","date_first_available"]].to_csv(out_prod, index=False)
print(f"\n  ✅ Saved preview: products_clean_preview.csv")

# ══════════════════════════════════════════════════════════════
# 2. REES46 — eCommerce Behavior Data
# ══════════════════════════════════════════════════════════════
section("LOADING REES46 (2019-Nov.csv) — may take 30-60 sec...")
rees = pd.read_csv(REES46_FILE)

section("REES46 RAW — Basic Info")
print(f"  Rows          : {len(rees):,}")
print(f"  Columns       : {rees.shape[1]}")
print(f"  Column names  : {list(rees.columns)}")

section("REES46 — Null counts")
for col in rees.columns:
    nulls = rees[col].isnull().sum()
    pct   = nulls / len(rees) * 100
    print(f"  {col:<25} {nulls:>8,} nulls  ({pct:.1f}%)")

section("REES46 — Event type breakdown")
print(rees["event_type"].value_counts().to_string())

section("REES46 — Top 20 category_code values")
print(rees["category_code"].value_counts().head(20).to_string())

section("REES46 — Filtering to furniture.*")
furniture_events = rees[
    rees["category_code"].str.startswith("furniture", na=False)
].copy()

print(f"  Total rows         : {len(rees):,}")
print(f"  Furniture rows     : {len(furniture_events):,}")
print(f"  % of total         : {len(furniture_events)/len(rees)*100:.2f}%")
print(f"\n  Furniture sub-categories:")
print(furniture_events["category_code"].value_counts().to_string())
print(f"\n  Event type breakdown (furniture only):")
print(furniture_events["event_type"].value_counts().to_string())
print(f"\n  Price stats (furniture events):")
print(furniture_events["price"].describe().to_string())
print(f"\n  Top 10 brands (furniture):")
print(furniture_events["brand"].value_counts().head(10).to_string())

print(f"\n  Date range:")
furniture_events["event_time"] = pd.to_datetime(furniture_events["event_time"], errors="coerce")
print(f"    From : {furniture_events['event_time'].min()}")
print(f"    To   : {furniture_events['event_time'].max()}")

print(f"\n  Nulls in key columns (furniture subset):")
for col in ["user_id","product_id","category_code","price","brand"]:
    nulls = furniture_events[col].isnull().sum()
    print(f"    {col:<20} {nulls:,} nulls ({nulls/len(furniture_events)*100:.1f}%)")

out_events = os.path.join(BASE, "furniture_events.csv")
furniture_events.to_csv(out_events, index=False)
print(f"\n  ✅ Saved: furniture_events.csv ({len(furniture_events):,} rows)")

# ══════════════════════════════════════════════════════════════
# 3. FINAL SUMMARY
# ══════════════════════════════════════════════════════════════
section("DAY 1 COMPLETE — What we're working with")
print(f"""
  furniture_events.csv  (from REES46)
  ├─ Rows     : {len(furniture_events):,}
  ├─ Columns  : {furniture_events.shape[1]}
  ├─ Use for  : stg_user_events -> fact_user_events
  └─ Key cols : event_type, product_id, category_code, price, user_id, brand

  superstore.csv  (Amazon furniture products)
  ├─ Rows     : {len(prod):,}
  ├─ Columns  : {prod.shape[1]}
  ├─ Use for  : stg_products -> dim_products
  └─ Key cols : asin, title, brand, price, main_category, sub_category, material

  Next -> Day 3: MySQL staging tables + LOAD DATA
""")
