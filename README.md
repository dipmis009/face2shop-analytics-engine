# 🛋️ Face2Shop Analytics Engine

> End-to-end furniture retail analytics pipeline — real ecommerce data, MySQL ETL, Power BI dashboard, Python automation

![Python](https://img.shields.io/badge/Python-3.9-blue?logo=python)
![MySQL](https://img.shields.io/badge/MySQL-8.0-orange?logo=mysql)
![PowerBI](https://img.shields.io/badge/Power%20BI-Dashboard-yellow?logo=powerbi)
![Status](https://img.shields.io/badge/Status-In%20Progress-green)

---

## 📌 Project Overview

This project simulates a real-world analytics platform for a furniture retail marketplace. Starting from raw ecommerce event data, it builds a complete pipeline from ingestion through to an interactive Power BI dashboard — the kind of end-to-end system a data analyst would own in a mid-size retail or marketplace company.

**Business Questions Answered:**
- Where do users drop off in the view → cart → purchase funnel?
- Which room types and price segments convert best?
- Which products have high traffic but zero purchases (gap analysis)?
- When are users most likely to purchase (peak hour analysis)?
- Which brands drive the most revenue?

---

## 🗂️ Dataset

| Dataset | Source | Rows | Used For |
|---|---|---|---|
| REES46 eCommerce Behavior (Nov 2019) | [Kaggle](https://www.kaggle.com/datasets/mkechinov/ecommerce-behavior-data-from-multi-category-store) | 2.1M (filtered) | User events — view, cart, purchase funnel |
| Amazon Furniture Products | [Kaggle](https://www.kaggle.com/datasets/kanchana1990/e-commerce-furniture-dataset-2024) | 203 | Product catalog — price, material, category |

> Full datasets are not included in this repo due to size. Sample data (100 rows) is available in `data/sample/`. See **How to Run** to reproduce from source.

---

## 🏗️ Architecture

```
Raw CSVs
   │
   ▼
┌─────────────────────────────────────────┐
│         Python ETL Pipeline             │
│  explore.py → 01_staging.py             │
│  02_cleaning.py → 03_modeling.py        │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│           MySQL (face2shop_db)          │
│                                         │
│  Staging      → stg_user_events         │
│                 stg_products            │
│                                         │
│  Clean        → clean_user_events       │
│                 clean_products          │
│                                         │
│  Star Schema  → fact_user_events        │
│                 dim_products            │
│                 dim_date                │
│                                         │
│  Views (x7)   → vw_conversion_funnel    │
│                 vw_room_performance     │
│                 vw_price_segment_analysis│
│                 vw_brand_performance    │
│                 vw_daily_trend          │
│                 vw_hourly_behavior      │
│                 vw_high_view_no_purchase│
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│         Power BI Dashboard              │
│  Page 1: Business Overview              │
│  Page 2: Funnel & Behavior              │
│  Page 3: Product & Gap Analysis         │
└─────────────────────────────────────────┘
```

---

## 📊 Key Findings

| Insight | Finding |
|---|---|
| **Funnel drop-off** | 97.5% of users who view never purchase — 282K viewers, only 8K buyers |
| **Best converting room** | Kitchen (0.81% CVR) despite lower traffic than living room |
| **Price vs conversion** | Budget segment converts 3x better than Luxury (0.75% vs 0.23%) |
| **Revenue driver** | Premium segment generates the most revenue despite mid-range conversion |
| **Peak purchase hour** | 9AM is the #1 purchase hour — morning intent is highest |
| **Gap analysis** | Product 14701881 has 3,419 views and 0 purchases — pricing or trust issue |

---

## 🗃️ Repo Structure

```
face2shop-analytics-engine/
│
├── python/
│   ├── explore.py            # Day 1: Dataset exploration + DQ baseline
│   ├── 01_staging.py         # Day 3: Create staging tables + load CSVs
│   ├── 02_cleaning.py        # Day 5: Clean + transform + enrich data
│   └── 03_modeling.py        # Day 7: Star schema + views + insight queries
│
├── data/
│   └── sample/
│       ├── furniture_events_sample.csv     # 100-row sample (REES46 filtered)
│       └── amazon_furniture_products.csv   # Full product catalog (203 rows)
│
├── dashboard/                # Power BI .pbix file + screenshots (Week 2)
│
├── docs/                     # Architecture diagrams, DQ report
│
└── README.md
```

---

## ⚙️ How to Run

### Prerequisites
- Python 3.9+
- MySQL 8.0
- Packages: `pandas sqlalchemy mysql-connector-python openpyxl`

```bash
pip3 install pandas sqlalchemy mysql-connector-python openpyxl
```

### Steps

**1. Download datasets**
- REES46: `kaggle datasets download -d mkechinov/ecommerce-behavior-data-from-multi-category-store -f 2019-Nov.csv --unzip`
- Amazon Products: `kaggle datasets download -d kanchana1990/e-commerce-furniture-dataset-2024 --unzip`

**2. Create MySQL database**
```sql
CREATE DATABASE face2shop_db;
```

**3. Run the pipeline in order**
```bash
python3 python/explore.py        # Explore + filter to furniture rows
python3 python/01_staging.py     # Create staging tables + load data
python3 python/02_cleaning.py    # Clean + enrich
python3 python/03_modeling.py    # Build star schema + views + insights
```

Each script will prompt for your MySQL root password.

---

## 🛠️ Tech Stack

| Tool | Purpose |
|---|---|
| Python (pandas, sqlalchemy) | ETL pipeline, data cleaning, automation |
| MySQL 8.0 | Staging, cleaning, star schema, analytical views |
| Power BI Desktop | Interactive dashboard (3 pages) |
| GitHub | Version control + portfolio |

---

## 👩‍💻 Author

**Dipali** — Data & Analytics Professional  
4 years experience across Deloitte and analytics consulting  
Skills: SQL · Python · Power BI · ETL · AWS  

[LinkedIn](#) · [GitHub](#)

---

## 🚧 Status

| Week | Task | Status |
|---|---|---|
| Week 1 | Data Ingestion + SQL ETL | ✅ Complete |
| Week 2 | Power BI Dashboard | 🔄 In Progress |
| Week 3 | Python Automation | ⏳ Upcoming |
| Week 4 | Interview Prep | ⏳ Upcoming |
