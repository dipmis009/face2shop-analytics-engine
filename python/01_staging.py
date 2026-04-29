import pandas as pd 
import ast 
import os 
import mysql.connector 
from sqlalchemy import create_engine, text

# ── Config ─────────────────────────────────────────────────────
BASE     = os.path.expanduser("~/Downloads/Furniture_retail")
DB_USER  = "root"
DB_PASS  = input("Enter your MySQL root password: ")
DB_HOST  = "127.0.0.1"
DB_PORT  = 3306
DB_NAME  = "face2shop_db"

engine = create_engine( "mysql+mysqlconnector://", creator=lambda: mysql.connector.connect( user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT, database=DB_NAME ) )
def section(title):
    print("\n" + "═" * 60)
    print(f"  {title}")
    print("═" * 60)

# ══════════════════════════════════════════════════════════════
# STEP 1: CREATE STAGING TABLES
# ══════════════════════════════════════════════════════════════
section("STEP 1 — Creating staging tables...")

with engine.connect() as conn:

    # Drop if exists (clean slate)
    conn.execute(text("DROP TABLE IF EXISTS stg_user_events"))
    conn.execute(text("DROP TABLE IF EXISTS stg_products"))
    conn.commit()

    # stg_user_events — from furniture_events.csv (REES46)
    conn.execute(text("""
        CREATE TABLE stg_user_events (
            event_time      VARCHAR(50),
            event_type      VARCHAR(20),
            product_id      BIGINT,
            category_id     BIGINT,
            category_code   VARCHAR(100),
            brand           VARCHAR(100),
            price           VARCHAR(20),
            user_id         BIGINT,
            user_session    VARCHAR(50),
            loaded_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    print("  ✅ stg_user_events created")

    # stg_products — from superstore.csv (Amazon furniture)
    conn.execute(text("""
        CREATE TABLE stg_products (
            asin                    VARCHAR(20),
            title                   TEXT,
            brand                   VARCHAR(200),
            price                   VARCHAR(20),
            availability            VARCHAR(100),
            categories              TEXT,
            material                VARCHAR(100),
            color                   VARCHAR(100),
            style                   VARCHAR(100),
            country_of_origin       VARCHAR(100),
            date_first_available    VARCHAR(50),
            package_dimensions      VARCHAR(100),
            manufacturer            VARCHAR(200),
            loaded_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))
    print("  ✅ stg_products created")
    conn.commit()

# ══════════════════════════════════════════════════════════════
# STEP 2: LOAD furniture_events.csv → stg_user_events
# ══════════════════════════════════════════════════════════════
section("STEP 2 — Loading furniture_events.csv into stg_user_events...")
print("  Reading file... (may take 20–30 sec)")

events = pd.read_csv(
    os.path.join(BASE, "furniture_events.csv"),
    dtype={
        "product_id":   str,
        "category_id":  str,
        "user_id":      str,
        "price":        str,
    }
)

print(f"  Rows read      : {len(events):,}")

# Keep only columns that match staging table
events_stg = events[[
    "event_time", "event_type", "product_id", "category_id",
    "category_code", "brand", "price", "user_id", "user_session"
]].copy()

# Load in chunks (2.1M rows — do in batches of 50K)
CHUNK = 50_000
total  = len(events_stg)
loaded = 0

for i in range(0, total, CHUNK):
    chunk = events_stg.iloc[i:i+CHUNK]
    chunk.to_sql(
        "stg_user_events",
        con=engine,
        if_exists="append",
        index=False,
        method="multi"
    )
    loaded += len(chunk)
    print(f"  Loaded {loaded:,} / {total:,} rows...", end="\r")

print(f"\n  ✅ stg_user_events loaded — {loaded:,} rows")

# ══════════════════════════════════════════════════════════════
# STEP 3: LOAD superstore.csv → stg_products
# ══════════════════════════════════════════════════════════════
section("STEP 3 — Loading superstore.csv into stg_products...")

prod = pd.read_csv(
    os.path.join(BASE, "superstore.csv"),
    encoding="latin1"
)

print(f"  Rows read      : {len(prod):,}")

# Parse categories list → extract main + sub
def extract_cat(cat_str, idx):
    try:
        cats = ast.literal_eval(str(cat_str))
        return cats[idx] if len(cats) > idx else None
    except:
        return None

prod["main_category"] = prod["categories"].apply(lambda x: extract_cat(x, 1))
prod["sub_category"]  = prod["categories"].apply(lambda x: extract_cat(x, 2))

# Keep only columns that match staging table
prod_stg = prod[[
    "asin", "title", "brand", "price", "availability",
    "categories", "material", "color", "style",
    "country_of_origin", "date_first_available",
    "package_dimensions", "manufacturer"
]].copy()

prod_stg.to_sql(
    "stg_products",
    con=engine,
    if_exists="append",
    index=False,
    method="multi"
)
print(f"  ✅ stg_products loaded — {len(prod_stg):,} rows")

# ══════════════════════════════════════════════════════════════
# STEP 4: VERIFY ROW COUNTS IN MYSQL
# ══════════════════════════════════════════════════════════════
section("STEP 4 — Verifying row counts in MySQL...")

with engine.connect() as conn:
    for table in ["stg_user_events", "stg_products"]:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
        count  = result.fetchone()[0]
        print(f"  {table:<25} : {count:,} rows")

# ══════════════════════════════════════════════════════════════
# STEP 5: QUICK DATA QUALITY CHECK IN MYSQL
# ══════════════════════════════════════════════════════════════
section("STEP 5 — DQ checks on staging tables...")

checks = {
    "stg_user_events — event_type values": """
        SELECT event_type, COUNT(*) as cnt
        FROM stg_user_events
        GROUP BY event_type
    """,
    "stg_user_events — null brands": """
        SELECT COUNT(*) as null_brands
        FROM stg_user_events
        WHERE brand IS NULL OR brand = ''
    """,
    "stg_user_events — price = 0": """
        SELECT COUNT(*) as zero_price_events
        FROM stg_user_events
        WHERE CAST(price AS DECIMAL(10,2)) = 0
    """,
    "stg_products — null prices": """
        SELECT COUNT(*) as null_prices
        FROM stg_products
        WHERE price IS NULL OR price = 'nan'
    """,
    "stg_products — main categories": """
        SELECT
            TRIM(SUBSTRING_INDEX(SUBSTRING_INDEX(
                REPLACE(REPLACE(categories, '[', ''), ']', ''),
                ',', 2), ',', -1)
            ) AS main_cat,
            COUNT(*) as cnt
        FROM stg_products
        GROUP BY main_cat
        ORDER BY cnt DESC
        LIMIT 8
    """,
}

with engine.connect() as conn:
    for label, query in checks.items():
        print(f"\n  {label}:")
        result = conn.execute(text(query))
        for row in result:
            print(f"    {row}")

section("DAY 3 COMPLETE ✅")
print("""
  Both staging tables are live in face2shop_db:
  ├─ stg_user_events  → 2.1M rows
  └─ stg_products     → 312 rows

  Next → Day 5: Cleaning & Transformation (02_cleaning.sql)
""")
