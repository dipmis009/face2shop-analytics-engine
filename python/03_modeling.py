import pandas as pd
import mysql.connector
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
# STEP 1: BUILD dim_products
# ══════════════════════════════════════════════════════════════
section("STEP 1 — Building dim_products...")

prod = pd.read_sql("SELECT * FROM clean_products", engine)

# Assign surrogate key
prod.insert(0, "product_key", range(1, len(prod) + 1))

# Fix material None → Unknown
prod["material"] = prod["material"].replace("None", "Unknown").fillna("Unknown")

# Add in_stock flag
prod["in_stock_flag"] = prod["availability"].apply(
    lambda x: 1 if x == "In Stock" else 0
)

# Final dim_products columns
dim_products = prod[[
    "product_key", "asin", "title", "brand",
    "price", "price_segment", "main_category",
    "sub_category", "availability", "in_stock_flag",
    "material", "color", "style", "country_of_origin",
    "date_first_available", "manufacturer"
]].copy()

with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS dim_products"))
    conn.commit()

dim_products.to_sql("dim_products", con=engine,
                    if_exists="replace", index=False, method="multi")

print(f"  ✅ dim_products — {len(dim_products):,} rows")
print(f"\n  Sub-category distribution:")
print(dim_products["sub_category"].value_counts().to_string())
print(f"\n  Price segment distribution:")
print(dim_products["price_segment"].value_counts().to_string())

# ══════════════════════════════════════════════════════════════
# STEP 2: BUILD dim_date
# ══════════════════════════════════════════════════════════════
section("STEP 2 — Building dim_date...")

# Read only date columns from clean_user_events
date_df = pd.read_sql("""
    SELECT DISTINCT
        event_date,
        year,
        month,
        month_name,
        week_number,
        day_of_week,
        day_type
    FROM clean_user_events
    ORDER BY event_date
""", engine)

date_df["event_date"] = pd.to_datetime(date_df["event_date"])

# Add extra date attributes
date_df["quarter"]        = date_df["event_date"].dt.quarter
date_df["quarter_name"]   = "Q" + date_df["quarter"].astype(str)
date_df["is_month_start"] = date_df["event_date"].dt.is_month_start.astype(int)
date_df["is_month_end"]   = date_df["event_date"].dt.is_month_end.astype(int)

with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS dim_date"))
    conn.commit()

date_df.to_sql("dim_date", con=engine,
               if_exists="replace", index=False, method="multi")

print(f"  ✅ dim_date — {len(date_df):,} rows (unique dates)")
print(f"\n  Date range:")
print(f"    From : {date_df['event_date'].min().date()}")
print(f"    To   : {date_df['event_date'].max().date()}")
print(f"\n  Day type split:")
print(date_df["day_type"].value_counts().to_string())

# ══════════════════════════════════════════════════════════════
# STEP 3: BUILD fact_user_events
# ══════════════════════════════════════════════════════════════
section("STEP 3 — Building fact_user_events...")

events = pd.read_sql("SELECT * FROM clean_user_events", engine)
print(f"  Events loaded : {len(events):,}")

# Add revenue column — only for purchases, zero-price excluded
events["revenue"] = events.apply(
    lambda r: r["price"] if (r["event_type"] == "purchase" and r["is_zero_price"] == 0)
    else 0.0,
    axis=1
)

# Add is_purchase / is_cart / is_view flags (useful for DAX in Power BI)
events["is_view"]     = (events["event_type"] == "view").astype(int)
events["is_cart"]     = (events["event_type"] == "cart").astype(int)
events["is_purchase"] = (events["event_type"] == "purchase").astype(int)

# Final fact table columns
fact = events[[
    "user_id", "user_session", "product_id", "event_type",
    "event_time", "event_date", "event_hour",
    "category_code", "room_type", "item_type",
    "brand", "price", "price_segment", "revenue",
    "is_view", "is_cart", "is_purchase", "is_zero_price",
    "year", "month", "month_name", "week_number",
    "day_of_week", "day_type"
]].copy()

with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS fact_user_events"))
    conn.commit()

CHUNK = 50_000
total  = len(fact)
loaded = 0
for i in range(0, total, CHUNK):
    chunk = fact.iloc[i:i+CHUNK]
    chunk.to_sql("fact_user_events", con=engine,
                 if_exists="append", index=False, method="multi")
    loaded += len(chunk)
    print(f"  Loaded {loaded:,} / {total:,} rows...", end="\r")

print(f"\n  ✅ fact_user_events — {loaded:,} rows")

# ══════════════════════════════════════════════════════════════
# STEP 4: CREATE ANALYTICAL VIEWS
# ══════════════════════════════════════════════════════════════
section("STEP 4 — Creating analytical views...")

views = {

"vw_conversion_funnel": """
    SELECT
        event_type,
        COUNT(*)                            AS event_count,
        COUNT(DISTINCT user_id)             AS unique_users,
        COUNT(DISTINCT user_session)        AS unique_sessions,
        ROUND(COUNT(*) * 100.0 /
            SUM(COUNT(*)) OVER (), 2)       AS pct_of_total
    FROM fact_user_events
    GROUP BY event_type
""",

"vw_room_performance": """
    SELECT
        room_type,
        item_type,
        COUNT(CASE WHEN event_type='view'     THEN 1 END)    AS views,
        COUNT(CASE WHEN event_type='cart'     THEN 1 END)    AS cart_adds,
        COUNT(CASE WHEN event_type='purchase' THEN 1 END)    AS purchases,
        ROUND(SUM(revenue), 2)                                AS total_revenue,
        ROUND(
            COUNT(CASE WHEN event_type='purchase' THEN 1 END) * 100.0 /
            NULLIF(COUNT(CASE WHEN event_type='view' THEN 1 END), 0)
        , 2)                                                  AS conversion_rate_pct
    FROM fact_user_events
    GROUP BY room_type, item_type
    ORDER BY total_revenue DESC
""",

"vw_price_segment_analysis": """
    SELECT
        price_segment,
        COUNT(CASE WHEN event_type='view'     THEN 1 END)    AS views,
        COUNT(CASE WHEN event_type='cart'     THEN 1 END)    AS cart_adds,
        COUNT(CASE WHEN event_type='purchase' THEN 1 END)    AS purchases,
        ROUND(SUM(revenue), 2)                                AS total_revenue,
        ROUND(
            COUNT(CASE WHEN event_type='purchase' THEN 1 END) * 100.0 /
            NULLIF(COUNT(CASE WHEN event_type='view' THEN 1 END), 0)
        , 2)                                                  AS conversion_rate_pct,
        ROUND(AVG(CASE WHEN event_type='purchase' THEN price END), 2) AS avg_purchase_price
    FROM fact_user_events
    WHERE is_zero_price = 0
    GROUP BY price_segment
    ORDER BY conversion_rate_pct DESC
""",

"vw_brand_performance": """
    SELECT
        brand,
        COUNT(CASE WHEN event_type='view'     THEN 1 END)    AS views,
        COUNT(CASE WHEN event_type='cart'     THEN 1 END)    AS cart_adds,
        COUNT(CASE WHEN event_type='purchase' THEN 1 END)    AS purchases,
        ROUND(SUM(revenue), 2)                                AS total_revenue,
        ROUND(
            COUNT(CASE WHEN event_type='purchase' THEN 1 END) * 100.0 /
            NULLIF(COUNT(CASE WHEN event_type='view' THEN 1 END), 0)
        , 2)                                                  AS conversion_rate_pct
    FROM fact_user_events
    WHERE brand != 'Unknown' AND is_zero_price = 0
    GROUP BY brand
    HAVING views > 100
    ORDER BY total_revenue DESC
""",

"vw_daily_trend": """
    SELECT
        event_date,
        year,
        month,
        month_name,
        week_number,
        day_of_week,
        day_type,
        COUNT(CASE WHEN event_type='view'     THEN 1 END)    AS views,
        COUNT(CASE WHEN event_type='cart'     THEN 1 END)    AS cart_adds,
        COUNT(CASE WHEN event_type='purchase' THEN 1 END)    AS purchases,
        ROUND(SUM(revenue), 2)                                AS daily_revenue,
        COUNT(DISTINCT user_id)                               AS active_users,
        COUNT(DISTINCT user_session)                          AS sessions
    FROM fact_user_events
    GROUP BY event_date, year, month, month_name,
             week_number, day_of_week, day_type
    ORDER BY event_date
""",

"vw_hourly_behavior": """
    SELECT
        event_hour,
        day_type,
        COUNT(CASE WHEN event_type='view'     THEN 1 END)    AS views,
        COUNT(CASE WHEN event_type='cart'     THEN 1 END)    AS cart_adds,
        COUNT(CASE WHEN event_type='purchase' THEN 1 END)    AS purchases,
        ROUND(SUM(revenue), 2)                                AS revenue
    FROM fact_user_events
    GROUP BY event_hour, day_type
    ORDER BY event_hour
""",

"vw_high_view_no_purchase": """
    SELECT
        product_id,
        brand,
        room_type,
        item_type,
        price_segment,
        COUNT(CASE WHEN event_type='view'     THEN 1 END)    AS views,
        COUNT(CASE WHEN event_type='cart'     THEN 1 END)    AS cart_adds,
        COUNT(CASE WHEN event_type='purchase' THEN 1 END)    AS purchases,
        ROUND(AVG(price), 2)                                  AS avg_price
    FROM fact_user_events
    GROUP BY product_id, brand, room_type, item_type, price_segment
    HAVING views > 500 AND purchases = 0
    ORDER BY views DESC
    LIMIT 30
""",

}

with engine.connect() as conn:
    for view_name, view_sql in views.items():
        conn.execute(text(f"DROP VIEW IF EXISTS {view_name}"))
        conn.execute(text(f"CREATE VIEW {view_name} AS {view_sql}"))
        conn.commit()
        print(f"  ✅ {view_name}")

# ══════════════════════════════════════════════════════════════
# STEP 5: RUN INSIGHT QUERIES
# ══════════════════════════════════════════════════════════════
section("STEP 5 — Running insight queries...")

queries = {
    "Overall Conversion Funnel": "SELECT * FROM vw_conversion_funnel ORDER BY event_count DESC",

    "Best Converting Room Types": """
        SELECT room_type,
               SUM(views) AS views, SUM(purchases) AS purchases,
               ROUND(SUM(purchases)*100.0/NULLIF(SUM(views),0),2) AS cvr_pct,
               ROUND(SUM(total_revenue),2) AS revenue
        FROM vw_room_performance
        GROUP BY room_type
        ORDER BY cvr_pct DESC
    """,

    "Price Segment Conversion": """
        SELECT price_segment, views, purchases,
               conversion_rate_pct, total_revenue
        FROM vw_price_segment_analysis
        ORDER BY conversion_rate_pct DESC
    """,

    "Top 10 Brands by Revenue": """
        SELECT brand, views, purchases, total_revenue, conversion_rate_pct
        FROM vw_brand_performance
        ORDER BY total_revenue DESC
        LIMIT 10
    """,

    "Peak Shopping Hours": """
        SELECT event_hour,
               SUM(views) AS views,
               SUM(purchases) AS purchases,
               ROUND(SUM(revenue),2) AS revenue
        FROM vw_hourly_behavior
        GROUP BY event_hour
        ORDER BY purchases DESC
        LIMIT 8
    """,

    "High View - No Purchase (Gap Analysis)": """
        SELECT product_id, brand, room_type, item_type,
               price_segment, views, cart_adds, purchases
        FROM vw_high_view_no_purchase
        LIMIT 10
    """,
}

with engine.connect() as conn:
    for label, query in queries.items():
        print(f"\n  ── {label} ──")
        result = pd.read_sql(query, engine)
        print(result.to_string(index=False))

# ══════════════════════════════════════════════════════════════
# STEP 6: FINAL TABLE SUMMARY
# ══════════════════════════════════════════════════════════════
section("STEP 6 — Final schema summary...")

tables = ["stg_user_events", "stg_products",
          "clean_user_events", "clean_products",
          "dim_products", "dim_date", "fact_user_events"]

with engine.connect() as conn:
    for table in tables:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
        count  = result.fetchone()[0]
        print(f"  {table:<25} : {count:,} rows")

section("DAY 7 COMPLETE ✅")
print("""
  Star schema is live in face2shop_db:
  ├─ dim_products       → 203 rows
  ├─ dim_date           → 30 rows  (Nov 2019)
  ├─ fact_user_events   → 2.1M rows
  └─ 7 analytical views ready for Power BI

  Next → Week 2: Power BI Dashboard
""")
