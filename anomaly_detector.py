# =============================================================================
# Face2Shop Analytics Engine — Module 3: Anomaly & Alert System
# Runs daily, flags conversion anomalies, outputs watchlist CSV + alert log
# =============================================================================

import os
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy import stats
from sqlalchemy import create_engine, text
import mysql.connector
from dotenv import load_dotenv
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# -----------------------------------------------------------------------------
# CONFIG
# -----------------------------------------------------------------------------
load_dotenv()
DB_PASS = os.getenv("DB_PASS")

COLORS = {
    'navy':       '#1B2B4B',
    'terracotta': '#C8956C',
    'teal':       '#1E4D5C',
    'coral':      '#E8503A',
    'cream':      '#FAF6F0',
    'text':       '#6B6B6B',
}

OUTPUT_DIR   = "outputs/alerts"
WATCHLIST_DIR = "outputs/alerts/watchlists"
CHART_DIR    = "outputs/alerts/charts"
LOG_FILE     = "outputs/alerts/alert_log.jsonl"
RUN_DATE     = datetime.now().strftime("%Y-%m-%d")
RUN_TS       = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

for d in [OUTPUT_DIR, WATCHLIST_DIR, CHART_DIR]:
    os.makedirs(d, exist_ok=True)

# Alert thresholds
THRESHOLDS = {
    'min_views_for_analysis':  100,    # minimum views to be included
    'zero_purchase_min_views': 500,    # flag zero-purchase if views >= this
    'cvr_z_score_alert':      -2.0,    # z-score below this = alert
    'cvr_drop_pct':            20.0,   # % CVR drop vs 7-day avg = alert
    'revenue_opportunity_min': 500,    # min est. lost revenue to flag
    'high_views_percentile':   90,     # top X% by views = high traffic
}

# -----------------------------------------------------------------------------
# DATABASE
# -----------------------------------------------------------------------------
def get_engine():
    return create_engine(
        "mysql+mysqlconnector://",
        creator=lambda: mysql.connector.connect(
            user="root", password=DB_PASS,
            host="127.0.0.1", port=3306, database="face2shop_db"
        )
    )

def fetch(engine, sql):
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)

# -----------------------------------------------------------------------------
# DETECTOR 1: Zero-purchase high-traffic products
# -----------------------------------------------------------------------------
def detect_zero_purchase(engine):
    print("\n  [1] Zero-Purchase High-Traffic Detector")

    df = fetch(engine, f"""
        SELECT
            product_id,
            SUM(CASE WHEN event_type='view'     THEN 1 ELSE 0 END) AS views,
            SUM(CASE WHEN event_type='cart'     THEN 1 ELSE 0 END) AS cart_adds,
            SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS purchases,
            MAX(price)    AS price,
            MAX(brand)    AS brand,
            MAX(room_type) AS room_type,
            MAX(price_segment) AS price_segment
        FROM fact_user_events
        GROUP BY product_id
        HAVING purchases = 0
           AND views >= {THRESHOLDS['zero_purchase_min_views']}
        ORDER BY views DESC
    """)

    if df.empty:
        print("    ✓ No zero-purchase alerts")
        return df

    avg_price   = fetch(engine, "SELECT AVG(price) AS avg FROM fact_user_events WHERE event_type='purchase'").iloc[0]['avg']
    df['est_revenue_lost'] = (df['views'] * 0.005 * float(avg_price)).round(0)
    df['alert_type']       = 'ZERO_PURCHASE'
    df['severity']         = df['views'].apply(
        lambda v: 'CRITICAL' if v >= 2000 else 'HIGH' if v >= 1000 else 'MEDIUM')
    df['run_date']         = RUN_DATE

    print(f"    ⚠ {len(df)} products flagged")
    print(f"    Est. total revenue lost: ${df['est_revenue_lost'].sum():,.0f}")
    print(f"    Severity breakdown:")
    print(df['severity'].value_counts().to_string())
    print(f"\n    Top 5:")
    print(df[['product_id','views','cart_adds','price','room_type','severity']].head(5).to_string(index=False))

    return df

# -----------------------------------------------------------------------------
# DETECTOR 2: CVR anomalies (z-score based)
# -----------------------------------------------------------------------------
def detect_cvr_anomalies(engine):
    print("\n  [2] CVR Anomaly Detector (Z-Score)")

    df = fetch(engine, f"""
        SELECT
            product_id,
            SUM(CASE WHEN event_type='view'     THEN 1 ELSE 0 END) AS views,
            SUM(CASE WHEN event_type='cart'     THEN 1 ELSE 0 END) AS cart_adds,
            SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS purchases,
            MAX(price)         AS price,
            MAX(brand)         AS brand,
            MAX(room_type)     AS room_type,
            MAX(price_segment) AS price_segment
        FROM fact_user_events
        GROUP BY product_id
        HAVING views >= {THRESHOLDS['min_views_for_analysis']}
           AND purchases > 0
    """)

    df['cvr_pct']  = (df['purchases'] / df['views'] * 100).round(4)
    mean_cvr       = df['cvr_pct'].mean()
    std_cvr        = df['cvr_pct'].std()
    df['z_score']  = ((df['cvr_pct'] - mean_cvr) / std_cvr).round(3)

    avg_order = fetch(engine, """
        SELECT AVG(revenue) AS aov
        FROM fact_user_events
        WHERE event_type='purchase' AND revenue > 0
    """).iloc[0]['aov']

    anomalies = df[df['z_score'] < THRESHOLDS['cvr_z_score_alert']].copy()
    anomalies['expected_purchases'] = (anomalies['views'] * mean_cvr / 100).round(0)
    anomalies['purchase_gap']       = (anomalies['expected_purchases'] - anomalies['purchases']).round(0)
    anomalies['est_revenue_lost']   = (anomalies['purchase_gap'] * float(avg_order)).round(0)
    anomalies['alert_type']         = 'CVR_ANOMALY'
    anomalies['severity']           = anomalies['z_score'].apply(
        lambda z: 'CRITICAL' if z < -3 else 'HIGH' if z < -2.5 else 'MEDIUM')
    anomalies['run_date']           = RUN_DATE
    anomalies['mean_cvr_pct']       = round(mean_cvr, 4)

    print(f"    Products analyzed:  {len(df):,}")
    print(f"    Mean CVR:           {mean_cvr:.4f}%  |  Std: {std_cvr:.4f}%")
    print(f"    Anomalies flagged:  {len(anomalies)}")
    print(f"    Est. revenue lost:  ${anomalies['est_revenue_lost'].sum():,.0f}")
    print(f"    Severity breakdown:")
    if not anomalies.empty:
        print(anomalies['severity'].value_counts().to_string())
        print(f"\n    Top 5 by revenue impact:")
        print(anomalies.sort_values('est_revenue_lost', ascending=False)[
            ['product_id','views','purchases','cvr_pct','z_score','est_revenue_lost','severity']
        ].head(5).to_string(index=False))

    return anomalies

# -----------------------------------------------------------------------------
# DETECTOR 3: Daily CVR trend — detect drops vs 7-day rolling avg
# -----------------------------------------------------------------------------
def detect_daily_drops(engine):
    print("\n  [3] Daily CVR Drop Detector")

    df = fetch(engine, """
        SELECT
            event_date,
            SUM(CASE WHEN event_type='view'     THEN 1 ELSE 0 END) AS views,
            SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS purchases,
            SUM(revenue) AS revenue
        FROM fact_user_events
        GROUP BY event_date
        ORDER BY event_date
    """)

    df['event_date']  = pd.to_datetime(df['event_date'])
    df['cvr_pct']     = (df['purchases'] / df['views'] * 100).round(4)
    df['rolling_avg'] = df['cvr_pct'].rolling(7, min_periods=3).mean()
    df['cvr_vs_avg']  = ((df['cvr_pct'] - df['rolling_avg']) / df['rolling_avg'] * 100).round(2)
    df['rev_rolling'] = df['revenue'].rolling(7, min_periods=3).mean()
    df['rev_vs_avg']  = ((df['revenue'] - df['rev_rolling']) / df['rev_rolling'] * 100).round(2)

    drops = df[df['cvr_vs_avg'] < -THRESHOLDS['cvr_drop_pct']].copy()
    drops['alert_type'] = 'DAILY_CVR_DROP'
    drops['severity']   = drops['cvr_vs_avg'].apply(
        lambda x: 'CRITICAL' if x < -40 else 'HIGH' if x < -30 else 'MEDIUM')
    drops['run_date']   = RUN_DATE

    print(f"    Days analyzed:      {len(df)}")
    print(f"    CVR drop alerts:    {len(drops)}")
    if not drops.empty:
        print(f"    Worst drop:         {drops['cvr_vs_avg'].min():.1f}% on {drops.loc[drops['cvr_vs_avg'].idxmin(), 'event_date'].date()}")
        print(drops[['event_date','cvr_pct','rolling_avg','cvr_vs_avg','severity']].to_string(index=False))

    return df, drops

# -----------------------------------------------------------------------------
# DETECTOR 4: Room/Segment performance watch
# -----------------------------------------------------------------------------
def detect_segment_alerts(engine):
    print("\n  [4] Segment Performance Monitor")

    room_df = fetch(engine, """
        SELECT
            room_type,
            SUM(CASE WHEN event_type='view'     THEN 1 ELSE 0 END) AS views,
            SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS purchases,
            SUM(revenue) AS revenue
        FROM fact_user_events
        GROUP BY room_type
    """)
    room_df['cvr_pct']    = (room_df['purchases'] / room_df['views'] * 100).round(4)
    overall_cvr           = room_df['purchases'].sum() / room_df['views'].sum() * 100
    room_df['vs_avg_pct'] = ((room_df['cvr_pct'] - overall_cvr) / overall_cvr * 100).round(2)
    room_df['alert']      = room_df['vs_avg_pct'] < -20
    room_df['run_date']   = RUN_DATE

    seg_df = fetch(engine, """
        SELECT
            price_segment,
            SUM(CASE WHEN event_type='view'     THEN 1 ELSE 0 END) AS views,
            SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS purchases,
            SUM(revenue) AS revenue
        FROM fact_user_events
        GROUP BY price_segment
    """)
    seg_df['cvr_pct']    = (seg_df['purchases'] / seg_df['views'] * 100).round(4)
    seg_df['vs_avg_pct'] = ((seg_df['cvr_pct'] - overall_cvr) / overall_cvr * 100).round(2)
    seg_df['alert']      = seg_df['vs_avg_pct'] < -20
    seg_df['run_date']   = RUN_DATE

    print(f"    Overall CVR benchmark: {overall_cvr:.4f}%")
    print(f"\n    Room performance vs avg:")
    print(room_df[['room_type','views','purchases','cvr_pct','vs_avg_pct','alert']].to_string(index=False))
    print(f"\n    Segment performance vs avg:")
    print(seg_df[['price_segment','views','purchases','cvr_pct','vs_avg_pct','alert']].to_string(index=False))

    return room_df, seg_df

# -----------------------------------------------------------------------------
# ALERT LOG — append to JSONL file
# -----------------------------------------------------------------------------
def write_alert_log(zero_df, cvr_df, drops_df, room_df, seg_df):
    alerts = []

    for _, row in zero_df.iterrows():
        alerts.append({
            'timestamp':   RUN_TS,
            'alert_type':  'ZERO_PURCHASE',
            'severity':    row['severity'],
            'product_id':  str(row['product_id']),
            'views':       int(row['views']),
            'purchases':   0,
            'est_rev_lost': float(row['est_revenue_lost']),
            'room_type':   str(row.get('room_type', '')),
            'message':     f"Product {row['product_id']} has {int(row['views'])} views and 0 purchases"
        })

    for _, row in cvr_df.iterrows():
        alerts.append({
            'timestamp':   RUN_TS,
            'alert_type':  'CVR_ANOMALY',
            'severity':    row['severity'],
            'product_id':  str(row['product_id']),
            'cvr_pct':     float(row['cvr_pct']),
            'z_score':     float(row['z_score']),
            'est_rev_lost': float(row['est_revenue_lost']),
            'message':     f"Product {row['product_id']} CVR {row['cvr_pct']:.4f}% is {row['z_score']:.2f} std devs below mean"
        })

    for _, row in drops_df.iterrows():
        alerts.append({
            'timestamp':  RUN_TS,
            'alert_type': 'DAILY_CVR_DROP',
            'severity':   row['severity'],
            'date':       str(row['event_date'].date()),
            'cvr_pct':    float(row['cvr_pct']),
            'vs_avg_pct': float(row['cvr_vs_avg']),
            'message':    f"CVR dropped {row['cvr_vs_avg']:.1f}% vs 7-day rolling avg on {row['event_date'].date()}"
        })

    for _, row in room_df[room_df['alert']].iterrows():
        alerts.append({
            'timestamp':  RUN_TS,
            'alert_type': 'ROOM_UNDERPERFORM',
            'severity':   'MEDIUM',
            'segment':    str(row['room_type']),
            'cvr_pct':    float(row['cvr_pct']),
            'vs_avg_pct': float(row['vs_avg_pct']),
            'message':    f"Room '{row['room_type']}' CVR is {row['vs_avg_pct']:.1f}% below overall avg"
        })

    for _, row in seg_df[seg_df['alert']].iterrows():
        alerts.append({
            'timestamp':  RUN_TS,
            'alert_type': 'SEGMENT_UNDERPERFORM',
            'severity':   'MEDIUM',
            'segment':    str(row['price_segment']),
            'cvr_pct':    float(row['cvr_pct']),
            'vs_avg_pct': float(row['vs_avg_pct']),
            'message':    f"Segment '{row['price_segment']}' CVR is {row['vs_avg_pct']:.1f}% below overall avg"
        })

    with open(LOG_FILE, 'a') as f:
        for alert in alerts:
            f.write(json.dumps(alert) + '\n')

    print(f"\n  Alert log: {len(alerts)} alerts written → {LOG_FILE}")
    return alerts

# -----------------------------------------------------------------------------
# WATCHLIST CSV
# -----------------------------------------------------------------------------
def write_watchlist(zero_df, cvr_df):
    frames = []

    if not zero_df.empty:
        z = zero_df[['product_id','views','cart_adds','purchases',
                     'price','brand','room_type','price_segment',
                     'est_revenue_lost','severity','alert_type','run_date']].copy()
        frames.append(z)

    if not cvr_df.empty:
        c = cvr_df[['product_id','views','cart_adds','purchases',
                    'cvr_pct','z_score','est_revenue_lost',
                    'severity','alert_type','run_date']].copy()
        frames.append(c)

    if frames:
        watchlist = pd.concat(frames, ignore_index=True).sort_values(
            ['severity', 'est_revenue_lost'],
            ascending=[True, False]
        )
        path = f"{WATCHLIST_DIR}/watchlist_{RUN_DATE}.csv"
        watchlist.to_csv(path, index=False)
        print(f"  Watchlist: {len(watchlist)} products → {path}")
        return watchlist
    return pd.DataFrame()

# -----------------------------------------------------------------------------
# CHARTS
# -----------------------------------------------------------------------------
def build_alert_charts(zero_df, cvr_df, daily_df, room_df, seg_df):
    print("  Generating alert charts...")

    fig, axes = plt.subplots(2, 3, figsize=(16, 10), facecolor=COLORS['cream'])
    fig.suptitle(f'Face2Shop — Daily Alert Dashboard  ({RUN_DATE})',
                 fontsize=15, fontweight='bold', color=COLORS['navy'], y=1.01)

    # --- Chart 1: Zero-purchase by severity ---
    ax = axes[0, 0]
    if not zero_df.empty:
        sev_counts = zero_df['severity'].value_counts()
        colors_sev = {'CRITICAL': COLORS['coral'], 'HIGH': COLORS['terracotta'],
                      'MEDIUM': COLORS['teal']}
        bar_colors = [colors_sev.get(s, COLORS['navy']) for s in sev_counts.index]
        ax.bar(sev_counts.index, sev_counts.values, color=bar_colors, edgecolor='none')
        for i, (idx, val) in enumerate(sev_counts.items()):
            ax.text(i, val + 0.3, str(val), ha='center', fontsize=9,
                    fontweight='bold', color=COLORS['navy'])
    ax.set_facecolor(COLORS['cream'])
    ax.spines[['top', 'right']].set_visible(False)
    ax.set_title('Zero-Purchase Alerts by Severity', fontsize=10,
                 fontweight='bold', color=COLORS['navy'])
    ax.tick_params(labelsize=8)

    # --- Chart 2: Top zero-purchase products ---
    ax = axes[0, 1]
    if not zero_df.empty:
        top = zero_df.head(10)
        ax.barh(top['product_id'].astype(str), top['views'],
                color=COLORS['coral'], edgecolor='none', height=0.6)
        ax.set_facecolor(COLORS['cream'])
        ax.spines[['top', 'right']].set_visible(False)
        ax.set_title('Top Zero-Purchase Products (Views)', fontsize=10,
                     fontweight='bold', color=COLORS['navy'])
        ax.set_xlabel('Views', fontsize=8, color=COLORS['text'])
        ax.tick_params(labelsize=7)

    # --- Chart 3: CVR anomaly z-score distribution ---
    ax = axes[0, 2]
    if not cvr_df.empty:
        ax.hist(cvr_df['z_score'], bins=20, color=COLORS['teal'],
                edgecolor='none', alpha=0.8)
        ax.axvline(x=-2, color=COLORS['coral'], linestyle='--',
                   linewidth=1.5, label='z=-2 threshold')
        ax.axvline(x=-3, color=COLORS['coral'], linestyle=':',
                   linewidth=1.5, label='z=-3 critical')
        ax.set_facecolor(COLORS['cream'])
        ax.spines[['top', 'right']].set_visible(False)
        ax.set_title('CVR Anomaly Z-Score Distribution', fontsize=10,
                     fontweight='bold', color=COLORS['navy'])
        ax.set_xlabel('Z-Score', fontsize=8, color=COLORS['text'])
        ax.legend(fontsize=7, frameon=False)
        ax.tick_params(labelsize=8)

    # --- Chart 4: Daily CVR trend with rolling avg ---
    ax = axes[1, 0]
    ax.plot(daily_df['event_date'], daily_df['cvr_pct'],
            color=COLORS['navy'], linewidth=1.5, label='Daily CVR')
    ax.plot(daily_df['event_date'], daily_df['rolling_avg'],
            color=COLORS['terracotta'], linewidth=2,
            linestyle='--', label='7-day avg')
    drop_days = daily_df[daily_df['cvr_vs_avg'] < -THRESHOLDS['cvr_drop_pct']]
    if not drop_days.empty:
        ax.scatter(drop_days['event_date'], drop_days['cvr_pct'],
                   color=COLORS['coral'], zorder=5, s=50, label='Alert')
    ax.set_facecolor(COLORS['cream'])
    ax.spines[['top', 'right']].set_visible(False)
    ax.set_title('Daily CVR vs 7-Day Rolling Avg', fontsize=10,
                 fontweight='bold', color=COLORS['navy'])
    ax.set_ylabel('CVR %', fontsize=8, color=COLORS['text'])
    ax.legend(fontsize=7, frameon=False)
    ax.tick_params(axis='x', rotation=30, labelsize=6)
    ax.tick_params(axis='y', labelsize=8)

    # --- Chart 5: Room performance vs avg ---
    ax = axes[1, 1]
    room_sorted = room_df.sort_values('vs_avg_pct')
    colors_room = [COLORS['coral'] if a else COLORS['teal']
                   for a in room_sorted['alert']]
    ax.barh(room_sorted['room_type'], room_sorted['vs_avg_pct'],
            color=colors_room, edgecolor='none', height=0.5)
    ax.axvline(x=0, color=COLORS['navy'], linewidth=1)
    ax.axvline(x=-20, color=COLORS['coral'], linewidth=1,
               linestyle='--', label='-20% threshold')
    ax.set_facecolor(COLORS['cream'])
    ax.spines[['top', 'right']].set_visible(False)
    ax.set_title('Room CVR vs Overall Avg (%)', fontsize=10,
                 fontweight='bold', color=COLORS['navy'])
    ax.tick_params(labelsize=8)
    ax.legend(fontsize=7, frameon=False)

    # --- Chart 6: Segment performance vs avg ---
    ax = axes[1, 2]
    seg_sorted = seg_df.sort_values('vs_avg_pct')
    colors_seg = [COLORS['coral'] if a else COLORS['teal']
                  for a in seg_sorted['alert']]
    ax.barh(seg_sorted['price_segment'], seg_sorted['vs_avg_pct'],
            color=colors_seg, edgecolor='none', height=0.5)
    ax.axvline(x=0, color=COLORS['navy'], linewidth=1)
    ax.axvline(x=-20, color=COLORS['coral'], linewidth=1,
               linestyle='--', label='-20% threshold')
    ax.set_facecolor(COLORS['cream'])
    ax.spines[['top', 'right']].set_visible(False)
    ax.set_title('Segment CVR vs Overall Avg (%)', fontsize=10,
                 fontweight='bold', color=COLORS['navy'])
    ax.tick_params(labelsize=8)
    ax.legend(fontsize=7, frameon=False)

    plt.tight_layout()
    path = f"{CHART_DIR}/alert_dashboard_{RUN_DATE}.png"
    fig.savefig(path, dpi=150, bbox_inches='tight',
                facecolor=COLORS['cream'], edgecolor='none')
    plt.close(fig)
    print(f"    ✓ Alert dashboard saved: {path}")
    return path

# -----------------------------------------------------------------------------
# SUMMARY REPORT
# -----------------------------------------------------------------------------
def print_summary(zero_df, cvr_df, drops_df, room_df, seg_df, alerts):
    total_rev_at_risk = 0
    if not zero_df.empty:
        total_rev_at_risk += zero_df['est_revenue_lost'].sum()
    if not cvr_df.empty:
        total_rev_at_risk += cvr_df['est_revenue_lost'].sum()

    critical = sum(1 for a in alerts if a.get('severity') == 'CRITICAL')
    high     = sum(1 for a in alerts if a.get('severity') == 'HIGH')
    medium   = sum(1 for a in alerts if a.get('severity') == 'MEDIUM')

    print("\n" + "="*60)
    print("  DAILY ALERT SUMMARY")
    print("="*60)
    print(f"  Run date:            {RUN_DATE}")
    print(f"  Total alerts:        {len(alerts)}")
    print(f"    CRITICAL:          {critical}")
    print(f"    HIGH:              {high}")
    print(f"    MEDIUM:            {medium}")
    print(f"  Revenue at risk:     ${total_rev_at_risk:,.0f}")
    print(f"\n  Alert breakdown:")
    print(f"    Zero-purchase:     {len(zero_df)} products")
    print(f"    CVR anomalies:     {len(cvr_df)} products")
    print(f"    Daily CVR drops:   {len(drops_df)} days")
    room_alerts = room_df['alert'].sum() if not room_df.empty else 0
    seg_alerts  = seg_df['alert'].sum()  if not seg_df.empty  else 0
    print(f"    Room alerts:       {room_alerts}")
    print(f"    Segment alerts:    {seg_alerts}")
    print(f"\n  Outputs:")
    print(f"    Watchlist:         outputs/alerts/watchlists/watchlist_{RUN_DATE}.csv")
    print(f"    Alert log:         outputs/alerts/alert_log.jsonl")
    print(f"    Chart:             outputs/alerts/charts/alert_dashboard_{RUN_DATE}.png")

# -----------------------------------------------------------------------------
# SCHEDULER CHECK — show how to automate
# -----------------------------------------------------------------------------
def print_cron_instructions():
    script_path = os.path.abspath("anomaly_detector.py")
    venv_python = os.path.abspath("venv/bin/python")
    print(f"""
  To run this automatically every day at 8AM, add this cron job:
  Run: crontab -e
  Add: 0 8 * * * cd {os.path.dirname(script_path)} && {venv_python} {script_path} >> outputs/alerts/cron.log 2>&1
""")

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    print("\n" + "="*60)
    print("  Face2Shop Anomaly Detector — Starting")
    print(f"  Run: {RUN_TS}")
    print("="*60)

    engine = get_engine()

    print("\nRunning detectors...")
    zero_df           = detect_zero_purchase(engine)
    cvr_df            = detect_cvr_anomalies(engine)
    daily_df, drops_df = detect_daily_drops(engine)
    room_df, seg_df   = detect_segment_alerts(engine)

    print("\nWriting outputs...")
    alerts    = write_alert_log(zero_df, cvr_df, drops_df, room_df, seg_df)
    watchlist = write_watchlist(zero_df, cvr_df)
    build_alert_charts(zero_df, cvr_df, daily_df, room_df, seg_df)

    print_summary(zero_df, cvr_df, drops_df, room_df, seg_df, alerts)
    print_cron_instructions()

    print("="*60)
    print("  Anomaly Detector COMPLETE")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
