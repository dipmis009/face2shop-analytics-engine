import pandas as pd
import mysql.connector
import ast
import os
from sqlalchemy import create_engine, text

# ── Config ─────────────────────────────────────────────────────
BASE     = os.path.expanduser("~/Downloads/Furniture_retail")
DB_USER  = "root"
DB_PASS  = input("Enter your MySQL root password: ")
DB_HOST  = "127.0.0.1"
DB_PORT  = 3306
DB_NAME  = "face2shop_db"

engine = create_engine(
    "mysql+mysqlconnector://",
    creator=lambda: mysql.connector.connect(
        user=DB_USER,
        password=DB_PASS,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME
    )
)

def section(title):
    print("\n" + "═" * 60)
    print(f"  {title}")
    print("═" * 60)

# ══════════════════════════════════════════════════════════════
# STEP 1: CLEAN stg_user_events → clean_user_events
# ══════════════════════════════════════════════════════════════
section("STEP 1 — Reading stg_user_events from MySQL...")

events = pd.read_sql("SELECT * FROM stg_user_events", engine)
print(f"  Rows loaded : {len(events):,}")

section("STEP 1 — Cleaning user events...")

# 1a. Fill null brands
events["brand"] = events["brand"].fillna("Unknown")
print(f"  ✅ Null brands filled with 'Unknown'")

# 1b. Convert price to numeric
events["price"] = pd.to_numeric(events["price"], errors="coerce").fillna(0)

# 1c. Flag zero-price events (keep rows, flag them)
events["is_zero_price"] = (events["price"] == 0).astype(int)
zero_count = events["is_zero_price"].sum()
print(f"  ✅ Zero-price rows flagged : {zero_count:,}")

# 1d. Parse event_time to datetime
events["event_time"] = pd.to_datetime(events["event_time"], utc=True, errors="coerce")

# 1e. Extract date parts for dim_date
events["event_date"]    = events["event_time"].dt.date
events["event_hour"]    = events["event_time"].dt.hour
events["day_of_week"]   = events["event_time"].dt.day_name()
events["day_type"]      = events["event_time"].dt.dayofweek.apply(
                              lambda x: "Weekend" if x >= 5 else "Weekday"
                          )
events["week_number"]   = events["event_time"].dt.isocalendar().week.astype(int)
events["month"]         = events["event_time"].dt.month
events["month_name"]    = events["event_time"].dt.month_name()
events["year"]          = events["event_time"].dt.year

# 1f. Extract furniture sub-category (e.g. furniture.living_room.sofa → living_room.sofa)
events["furniture_type"] = events["category_code"].str.replace(
    "furniture.", "", regex=False
)

# 1g. Extract room type (living_room, bedroom, kitchen etc.)
events["room_type"] = events["category_code"].str.split(".").str[1]

# 1h. Extract item type (sofa, bed, chair etc.)
events["item_type"] = events["category_code"].str.split(".").str[2]

# 1i. Add price segment
def price_segment(p):
    if p == 0:      return "Unknown"
    elif p < 100:   return "Budget"
    elif p < 300:   return "Mid-Range"
    elif p < 700:   return "Premium"
    else:           return "Luxury"

events["price_segment"] = events["price"].apply(price_segment)

print(f"  ✅ Date parts extracted")
print(f"  ✅ Furniture type / room / item parsed")
print(f"  ✅ Price segments assigned")

section("STEP 1 — Clean events summary")
print(f"  Total rows          : {len(events):,}")
print(f"\n  Event type counts:")
print(events["event_type"].value_counts().to_string())
print(f"\n  Room type breakdown:")
print(events["room_type"].value_counts().to_string())
print(f"\n  Price segment breakdown:")
print(events["price_segment"].value_counts().to_string())
print(f"\n  Zero price rows     : {events['is_zero_price'].sum():,}")
print(f"  Null event_time     : {events['event_time'].isnull().sum():,}")

# ══════════════════════════════════════════════════════════════
# STEP 2: CLEAN stg_products → clean_products
# ══════════════════════════════════════════════════════════════
section("STEP 2 — Reading stg_products from MySQL...")

prod = pd.read_sql("SELECT * FROM stg_products", engine)
print(f"  Rows loaded : {len(prod):,}")

section("STEP 2 — Cleaning products...")

# 2a. Parse categories list → main_category, sub_category
def extract_cat(cat_str, idx):
    try:
        cats = ast.literal_eval(str(cat_str))
        # strip quotes and whitespace
        val = cats[idx].strip().strip("'\"") if len(cats) > idx else None
        return val
    except:
        return None

prod["main_category"] = prod["categories"].apply(lambda x: extract_cat(x, 1))
prod["sub_category"]  = prod["categories"].apply(lambda x: extract_cat(x, 2))

# 2b. Filter to Furniture main category only
before = len(prod)
prod = prod[prod["main_category"] == "Furniture"].copy()
print(f"  ✅ Filtered to Furniture only: {before} → {len(prod)} rows")

# 2c. Clean price: remove $, convert to numeric
prod["price_clean"] = (
    prod["price"]
    .astype(str)
    .str.replace("$", "", regex=False)
    .str.replace(",", "", regex=False)
    .str.strip()
)
prod["price_clean"] = pd.to_numeric(prod["price_clean"], errors="coerce")

# 2d. Fill null prices with sub_category median
median_by_subcat = prod.groupby("sub_category")["price_clean"].median()
def fill_price(row):
    if pd.isnull(row["price_clean"]):
        return median_by_subcat.get(row["sub_category"], prod["price_clean"].median())
    return row["price_clean"]

prod["price_clean"] = prod.apply(fill_price, axis=1)
print(f"  ✅ Null prices filled with sub-category median")

# 2e. Standardize availability
def clean_availability(val):
    if pd.isnull(val):
        return "Unknown"
    val = str(val).lower()
    if "in stock" in val:
        return "In Stock"
    if "out of stock" in val or "unavailable" in val:
        return "Out of Stock"
    if "temporarily" in val:
        return "Temporarily Unavailable"
    if "1-2 days" in val or "ship" in val:
        return "Ships Soon"
    return "Other"

prod["availability_clean"] = prod["availability"].apply(clean_availability)
print(f"  ✅ Availability standardized")
print(f"     {prod['availability_clean'].value_counts().to_dict()}")

# 2f. Clean brand — strip "Store" suffix (e.g. "Flash Furniture Store" → "Flash Furniture")
prod["brand_clean"] = (
    prod["brand"]
    .astype(str)
    .str.replace(" Store", "", regex=False)
    .str.strip()
)

# 2g. Clean material — title case, strip whitespace
prod["material_clean"] = prod["material"].astype(str).str.strip().str.title()
prod["material_clean"] = prod["material_clean"].replace("Nan", "Unknown")

# 2h. Add price segment (USD scale — different from events)
def price_seg_usd(p):
    if pd.isnull(p) or p == 0: return "Unknown"
    elif p < 30:   return "Budget"
    elif p < 80:   return "Mid-Range"
    elif p < 150:  return "Premium"
    else:          return "Luxury"

prod["price_segment"] = prod["price_clean"].apply(price_seg_usd)

# 2i. Parse date_first_available
prod["date_first_available"] = pd.to_datetime(
    prod["date_first_available"], errors="coerce"
)

section("STEP 2 — Clean products summary")
print(f"  Total rows          : {len(prod):,}")
print(f"\n  Sub-category breakdown:")
print(prod["sub_category"].value_counts().to_string())
print(f"\n  Price segment breakdown:")
print(prod["price_segment"].value_counts().to_string())
print(f"\n  Availability breakdown:")
print(prod["availability_clean"].value_counts().to_string())
print(f"\n  Material breakdown:")
print(prod["material_clean"].value_counts().head(10).to_string())
print(f"\n  Price stats (after fill):")
print(prod["price_clean"].describe().to_string())

# ══════════════════════════════════════════════════════════════
# STEP 3: WRITE CLEAN TABLES BACK TO MYSQL
# ══════════════════════════════════════════════════════════════
section("STEP 3 — Writing clean_user_events to MySQL...")

events_out = events[[
    "event_time", "event_date", "event_type", "product_id",
    "category_id", "category_code", "furniture_type", "room_type",
    "item_type", "brand", "price", "price_segment", "is_zero_price",
    "user_id", "user_session", "event_hour", "day_of_week",
    "day_type", "week_number", "month", "month_name", "year"
]]

with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS clean_user_events"))
    conn.commit()

CHUNK = 50_000
total  = len(events_out)
loaded = 0
for i in range(0, total, CHUNK):
    chunk = events_out.iloc[i:i+CHUNK]
    chunk.to_sql("clean_user_events", con=engine,
                 if_exists="append", index=False, method="multi")
    loaded += len(chunk)
    print(f"  Loaded {loaded:,} / {total:,} rows...", end="\r")

print(f"\n  ✅ clean_user_events written — {loaded:,} rows")

section("STEP 3 — Writing clean_products to MySQL...")

prod_out = prod[[
    "asin", "title", "brand_clean", "price_clean", "price_segment",
    "main_category", "sub_category", "availability_clean",
    "material_clean", "color", "style", "country_of_origin",
    "date_first_available", "manufacturer"
]].rename(columns={
    "brand_clean":        "brand",
    "price_clean":        "price",
    "availability_clean": "availability",
    "material_clean":     "material",
})

with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS clean_products"))
    conn.commit()

prod_out.to_sql("clean_products", con=engine,
                if_exists="replace", index=False, method="multi")
print(f"  ✅ clean_products written — {len(prod_out):,} rows")

# ══════════════════════════════════════════════════════════════
# STEP 4: VERIFY
# ══════════════════════════════════════════════════════════════
section("STEP 4 — Final verification...")

with engine.connect() as conn:
    for table in ["clean_user_events", "clean_products"]:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
        count  = result.fetchone()[0]
        print(f"  {table:<25} : {count:,} rows")

section("DAY 5 COMPLETE ✅")
print("""
  Clean tables live in face2shop_db:
  ├─ clean_user_events  → 2.1M rows (enriched with date parts, room/item type, price segment)
  └─ clean_products     → Furniture rows only (price filled, availability standardized)

  Next → Day 7: Star Schema Modeling (03_modeling.py)
""")
