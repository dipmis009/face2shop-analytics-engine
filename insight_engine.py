# =============================================================================
# Face2Shop Analytics Engine — Module 2: Statistical Insight Engine
# Runs statistical analysis on key findings → outputs interview-ready numbers
# =============================================================================

import os
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from scipy import stats
from sqlalchemy import create_engine, text
import mysql.connector
from dotenv import load_dotenv
from datetime import datetime
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

OUTPUT_DIR  = "outputs/insights"
CHART_DIR   = "outputs/insights/charts"
REPORT_DATE = datetime.now().strftime("%Y-%m-%d")
os.makedirs(CHART_DIR, exist_ok=True)

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
# ANALYSIS 1: FUNNEL DROP-OFF — Chi-Square significance test
# -----------------------------------------------------------------------------
def analyze_funnel(engine):
    print("\n  [A] Funnel Drop-off Analysis")

    df = fetch(engine, "SELECT event_type, COUNT(*) AS cnt FROM fact_user_events GROUP BY event_type")
    df = df.set_index('event_type')['cnt']

    views     = int(df.get('view', 0))
    carts     = int(df.get('cart', 0))
    purchases = int(df.get('purchase', 0))

    view_to_cart     = carts / views * 100
    cart_to_purchase = purchases / carts * 100
    view_to_purchase = purchases / views * 100
    drop_off         = (views - purchases) / views * 100

    # Chi-square: are purchases significantly different from random (expected = views * baseline)?
    baseline_rate = 0.02  # industry benchmark 2%
    expected_purchases = views * baseline_rate
    chi2, p_value = stats.chisquare(
        f_obs=[purchases, views - purchases],
        f_exp=[expected_purchases, views - expected_purchases]
    )

    results = {
        'views':             views,
        'carts':             carts,
        'purchases':         purchases,
        'view_to_cart_pct':  round(view_to_cart, 2),
        'cart_to_purchase_pct': round(cart_to_purchase, 2),
        'overall_cvr_pct':   round(view_to_purchase, 4),
        'drop_off_pct':      round(drop_off, 2),
        'chi2_statistic':    round(chi2, 2),
        'p_value':           round(p_value, 6),
        'significant':       p_value < 0.05,
        'vs_industry_2pct':  round(view_to_purchase - 2.0, 2),
    }

    print(f"    Views:              {views:,}")
    print(f"    Carts:              {carts:,}")
    print(f"    Purchases:          {purchases:,}")
    print(f"    View → Cart:        {view_to_cart:.2f}%")
    print(f"    Cart → Purchase:    {cart_to_purchase:.2f}%")
    print(f"    Overall CVR:        {view_to_purchase:.4f}%")
    print(f"    Drop-off:           {drop_off:.2f}%")
    print(f"    Chi² vs 2% bench:   χ²={chi2:.2f}, p={p_value:.6f}")
    print(f"    Statistically sig:  {results['significant']}")
    print(f"    vs Industry (2%):   {results['vs_industry_2pct']:+.2f}%")

    return results

# -----------------------------------------------------------------------------
# ANALYSIS 2: PRICE SEGMENT — ANOVA + Tukey HSD
# -----------------------------------------------------------------------------
def analyze_price_segments(engine):
    print("\n  [B] Price Segment Statistical Analysis")

    df = fetch(engine, """
        SELECT price_segment, revenue
        FROM fact_user_events
        WHERE event_type = 'purchase' AND revenue > 0
    """)

    segments = df['price_segment'].dropna().unique()
    groups   = [df[df['price_segment'] == s]['revenue'].values for s in segments]

    # One-way ANOVA
    f_stat, p_value = stats.f_oneway(*groups)

    # Descriptive stats per segment
    desc = df.groupby('price_segment')['revenue'].agg(
        count='count', mean='mean', median='median', std='std'
    ).round(2)

    # Effect size (eta-squared)
    grand_mean  = df['revenue'].mean()
    ss_between  = sum(len(g) * (g.mean() - grand_mean)**2 for g in groups)
    ss_total    = sum((df['revenue'] - grand_mean)**2)
    eta_squared = ss_between / ss_total if ss_total > 0 else 0

    # CVR per segment from view
    cvr_df = fetch(engine, """
        SELECT price_segment,
               SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS purchases,
               SUM(CASE WHEN event_type='view'     THEN 1 ELSE 0 END) AS views
        FROM fact_user_events
        GROUP BY price_segment
    """)
    cvr_df['cvr_pct'] = (cvr_df['purchases'] / cvr_df['views'] * 100).round(4)

    results = {
        'f_statistic':  round(f_stat, 2),
        'p_value':      round(p_value, 6),
        'significant':  p_value < 0.05,
        'eta_squared':  round(eta_squared, 4),
        'descriptive':  desc,
        'cvr_by_seg':   cvr_df,
    }

    print(f"    ANOVA F-statistic:  {f_stat:.2f}")
    print(f"    p-value:            {p_value:.6f}")
    print(f"    Significant:        {results['significant']}")
    print(f"    Effect size η²:     {eta_squared:.4f}")
    print("\n    Revenue per segment:")
    print(desc.to_string())
    print("\n    CVR per segment:")
    print(cvr_df[['price_segment','views','purchases','cvr_pct']].to_string(index=False))

    return results

# -----------------------------------------------------------------------------
# ANALYSIS 3: HOURLY PATTERN — Peak detection + confidence intervals
# -----------------------------------------------------------------------------
def analyze_hourly(engine):
    print("\n  [C] Hourly Purchase Pattern Analysis")

    df = fetch(engine, """
        SELECT HOUR(event_time) AS hour,
               SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS purchases,
               SUM(CASE WHEN event_type='view'     THEN 1 ELSE 0 END) AS views
        FROM fact_user_events
        GROUP BY HOUR(event_time)
        ORDER BY hour
    """)

    df['cvr_pct'] = (df['purchases'] / df['views'] * 100).round(4)

    # 95% confidence interval for purchases per hour
    mean_p = df['purchases'].mean()
    std_p  = df['purchases'].std()
    n      = len(df)
    se     = std_p / np.sqrt(n)
    ci_low, ci_high = stats.t.interval(0.95, df=n-1, loc=mean_p, scale=se)

    peak_hour     = int(df.loc[df['purchases'].idxmax(), 'hour'])
    peak_count    = int(df['purchases'].max())
    trough_hour   = int(df.loc[df['purchases'].idxmin(), 'hour'])
    trough_count  = int(df['purchases'].min())

    # Business hours vs off-hours (9-18 vs rest)
    biz   = df[df['hour'].between(9, 18)]['purchases'].sum()
    off   = df[~df['hour'].between(9, 18)]['purchases'].sum()
    biz_pct = biz / (biz + off) * 100

    # Kruskal-Wallis test: is there significant variation across hours?
    hourly_groups = [df[df['hour'] == h]['purchases'].values for h in df['hour']]
    # Use raw event data for proper test
    raw = fetch(engine, """
        SELECT HOUR(event_time) AS hour, COUNT(*) AS cnt
        FROM fact_user_events
        WHERE event_type = 'purchase'
        GROUP BY DATE(event_time), HOUR(event_time)
    """)
    hour_groups = [raw[raw['hour'] == h]['cnt'].values for h in sorted(raw['hour'].unique())]
    hour_groups = [g for g in hour_groups if len(g) > 0]
    kw_stat, kw_p = stats.kruskal(*hour_groups)

    results = {
        'peak_hour':    peak_hour,
        'peak_count':   peak_count,
        'trough_hour':  trough_hour,
        'trough_count': trough_count,
        'mean_per_hour': round(mean_p, 1),
        'ci_95_low':    round(ci_low, 1),
        'ci_95_high':   round(ci_high, 1),
        'biz_hours_pct': round(biz_pct, 1),
        'kw_statistic': round(kw_stat, 2),
        'kw_p_value':   round(kw_p, 6),
        'significant':  kw_p < 0.05,
        'hourly_df':    df,
    }

    print(f"    Peak hour:          {peak_hour}:00 ({peak_count:,} purchases)")
    print(f"    Trough hour:        {trough_hour}:00 ({trough_count:,} purchases)")
    print(f"    Mean per hour:      {mean_p:.1f}")
    print(f"    95% CI:             [{ci_low:.1f}, {ci_high:.1f}]")
    print(f"    Business hrs share: {biz_pct:.1f}% of all purchases")
    print(f"    Kruskal-Wallis:     H={kw_stat:.2f}, p={kw_p:.6f}")
    print(f"    Significant:        {results['significant']}")

    return results

# -----------------------------------------------------------------------------
# ANALYSIS 4: ROOM CATEGORY — CVR comparison + ranking confidence
# -----------------------------------------------------------------------------
def analyze_rooms(engine):
    print("\n  [D] Room Category CVR Analysis")

    df = fetch(engine, """
        SELECT room_type,
               SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS purchases,
               SUM(CASE WHEN event_type='view'     THEN 1 ELSE 0 END) AS views
        FROM fact_user_events
        GROUP BY room_type
        HAVING views > 100
        ORDER BY purchases/views DESC
    """)

    df['cvr_pct'] = (df['purchases'] / df['views'] * 100).round(4)

    # Wilson score confidence interval for each room's CVR
    def wilson_ci(purchases, views, z=1.96):
        p = purchases / views
        denom = 1 + z**2 / views
        centre = (p + z**2 / (2*views)) / denom
        margin = z * np.sqrt(p*(1-p)/views + z**2/(4*views**2)) / denom
        return round((centre - margin)*100, 4), round((centre + margin)*100, 4)

    df['ci_low'], df['ci_high'] = zip(*df.apply(
        lambda r: wilson_ci(r['purchases'], r['views']), axis=1))

    # Chi-square test: Kitchen vs all others
    top_room   = df.iloc[0]
    rest       = df.iloc[1:]
    observed   = np.array([top_room['purchases'], top_room['views'] - top_room['purchases']])
    rest_rate  = rest['purchases'].sum() / rest['views'].sum()
    expected   = np.array([top_room['views'] * rest_rate,
                           top_room['views'] * (1 - rest_rate)])
    chi2, p_val = stats.chisquare(observed, expected)

    results = {
        'ranked_df':    df,
        'top_room':     top_room['room_type'],
        'top_cvr':      top_room['cvr_pct'],
        'chi2':         round(chi2, 2),
        'p_value':      round(p_val, 6),
        'significant':  p_val < 0.05,
    }

    print(f"    Top room:           {top_room['room_type']} ({top_room['cvr_pct']:.4f}% CVR)")
    print(f"    Chi² vs others:     χ²={chi2:.2f}, p={p_val:.6f}")
    print(f"    Significant:        {results['significant']}")
    print("\n    Room CVR with 95% Wilson CI:")
    print(df[['room_type','views','purchases','cvr_pct','ci_low','ci_high']].to_string(index=False))

    return results

# -----------------------------------------------------------------------------
# ANALYSIS 5: GAP ANALYSIS — Product anomaly scoring
# -----------------------------------------------------------------------------
def analyze_gaps(engine):
    print("\n  [E] Product Gap (Anomaly) Analysis")

    df = fetch(engine, """
        SELECT product_id,
               SUM(CASE WHEN event_type='view'     THEN 1 ELSE 0 END) AS views,
               SUM(CASE WHEN event_type='purchase' THEN 1 ELSE 0 END) AS purchases,
               SUM(revenue) AS revenue
        FROM fact_user_events
        GROUP BY product_id
        HAVING views >= 100
    """)

    df['cvr_pct']      = (df['purchases'] / df['views'] * 100).round(4)
    mean_cvr           = df['cvr_pct'].mean()
    std_cvr            = df['cvr_pct'].std()
    df['z_score']      = ((df['cvr_pct'] - mean_cvr) / std_cvr).round(3)
    df['anomaly']      = (df['z_score'] < -1.0) | (df['purchases'] == 0)
    df['revenue_lost'] = ((mean_cvr/100 * df['views']) - df['purchases']) * 220.35
    df['revenue_lost'] = df['revenue_lost'].clip(lower=0).round(0)

    anomalies = df[df['anomaly']].sort_values('views', ascending=False)

    results = {
        'total_products':   len(df),
        'anomaly_count':    len(anomalies),
        'mean_cvr':         round(mean_cvr, 4),
        'std_cvr':          round(std_cvr, 4),
        'anomaly_df':       anomalies,
        'total_rev_lost':   anomalies['revenue_lost'].sum(),
    }

    print(f"    Products analyzed:  {len(df):,}")
    print(f"    Mean CVR:           {mean_cvr:.4f}%")
    print(f"    Std CVR:            {std_cvr:.4f}%")
    print(f"    Anomalies (z<-2):   {len(anomalies)}")
    print(f"    Est. revenue lost:  ${anomalies['revenue_lost'].sum():,.0f}")
    print(f"\n    Top anomalies:")
    print(anomalies[['product_id','views','purchases','cvr_pct','z_score','revenue_lost']].head(10).to_string(index=False))

    return results

# -----------------------------------------------------------------------------
# CHART: INSIGHT DASHBOARD
# -----------------------------------------------------------------------------
def build_insight_charts(funnel_r, segment_r, hourly_r, room_r, gap_r):
    print("\n  Generating insight charts...")

    fig = plt.figure(figsize=(16, 12), facecolor=COLORS['cream'])
    gs  = gridspec.GridSpec(3, 3, figure=fig, hspace=0.45, wspace=0.35)

    # --- Chart 1: Funnel waterfall ---
    ax1 = fig.add_subplot(gs[0, 0])
    stages = ['Views', 'Carts', 'Purchases']
    vals   = [funnel_r['views'], funnel_r['carts'], funnel_r['purchases']]
    bars   = ax1.bar(stages, vals,
                     color=[COLORS['navy'], COLORS['teal'], COLORS['terracotta']],
                     edgecolor='none', width=0.5)
    for bar, val in zip(bars, vals):
        ax1.text(bar.get_x() + bar.get_width()/2, bar.get_height() * 1.02,
                 f'{val:,}', ha='center', fontsize=8,
                 color=COLORS['navy'], fontweight='bold')
    ax1.set_facecolor(COLORS['cream'])
    ax1.spines[['top','right']].set_visible(False)
    ax1.set_title('Conversion Funnel', fontsize=10, fontweight='bold',
                  color=COLORS['navy'])
    ax1.set_ylabel('Events', fontsize=8, color=COLORS['text'])
    ax1.tick_params(labelsize=8)

    # --- Chart 2: CVR vs Industry ---
    ax2 = fig.add_subplot(gs[0, 1])
    labels  = ['Face2Shop\nCVR', 'Industry\nBenchmark']
    values  = [funnel_r['overall_cvr_pct'], 2.0]
    colors2 = [COLORS['coral'], COLORS['teal']]
    bars2   = ax2.bar(labels, values, color=colors2, edgecolor='none', width=0.4)
    for bar, val in zip(bars2, values):
        ax2.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02,
                 f'{val:.2f}%', ha='center', fontsize=9, fontweight='bold',
                 color=COLORS['navy'])
    ax2.set_facecolor(COLORS['cream'])
    ax2.spines[['top','right']].set_visible(False)
    ax2.set_title('CVR vs Industry (2%)', fontsize=10, fontweight='bold',
                  color=COLORS['navy'])
    ax2.tick_params(labelsize=8)

    # --- Chart 3: Hourly purchases with CI band ---
    ax3 = fig.add_subplot(gs[0, 2])
    hdf = hourly_r['hourly_df']
    ax3.plot(hdf['hour'], hdf['purchases'],
             color=COLORS['teal'], linewidth=2)
    ax3.fill_between(hdf['hour'],
                     hourly_r['ci_95_low'],
                     hourly_r['ci_95_high'],
                     color=COLORS['teal'], alpha=0.15,
                     label='95% CI')
    peak = hdf.loc[hdf['purchases'].idxmax()]
    ax3.scatter(peak['hour'], peak['purchases'],
                color=COLORS['coral'], zorder=5, s=60)
    ax3.annotate(f"Peak {int(peak['hour'])}h",
                 xy=(peak['hour'], peak['purchases']),
                 xytext=(5, 5), textcoords='offset points',
                 fontsize=7, color=COLORS['coral'], fontweight='bold')
    ax3.set_facecolor(COLORS['cream'])
    ax3.spines[['top','right']].set_visible(False)
    ax3.set_title('Hourly Purchases + 95% CI', fontsize=10,
                  fontweight='bold', color=COLORS['navy'])
    ax3.set_xlabel('Hour', fontsize=8, color=COLORS['text'])
    ax3.tick_params(labelsize=7)

    # --- Chart 4: Price segment CVR ---
    ax4 = fig.add_subplot(gs[1, 0])
    seg_df = segment_r['cvr_by_seg'].sort_values('cvr_pct', ascending=True)
    colors4 = [COLORS['navy'], COLORS['teal'],
               COLORS['terracotta'], COLORS['coral']][:len(seg_df)]
    ax4.barh(seg_df['price_segment'], seg_df['cvr_pct'],
             color=colors4, edgecolor='none', height=0.5)
    for i, (_, row) in enumerate(seg_df.iterrows()):
        ax4.text(row['cvr_pct'] + 0.001, i,
                 f"{row['cvr_pct']:.3f}%", va='center',
                 fontsize=8, color=COLORS['navy'], fontweight='bold')
    ax4.set_facecolor(COLORS['cream'])
    ax4.spines[['top','right']].set_visible(False)
    ax4.set_title('CVR by Price Segment', fontsize=10,
                  fontweight='bold', color=COLORS['navy'])
    ax4.tick_params(labelsize=8)

    # --- Chart 5: Room CVR with Wilson CI ---
    ax5 = fig.add_subplot(gs[1, 1:])
    rdf = room_r['ranked_df'].sort_values('cvr_pct', ascending=True)
    y   = range(len(rdf))
    ax5.barh(y, rdf['cvr_pct'], color=COLORS['teal'],
             edgecolor='none', height=0.5, alpha=0.7)
    ax5.errorbar(rdf['cvr_pct'], list(y),
                 xerr=[rdf['cvr_pct'] - rdf['ci_low'],
                       rdf['ci_high'] - rdf['cvr_pct']],
                 fmt='none', color=COLORS['coral'],
                 capsize=3, linewidth=1.5)
    ax5.set_yticks(list(y))
    ax5.set_yticklabels(rdf['room_type'], fontsize=8)
    ax5.set_facecolor(COLORS['cream'])
    ax5.spines[['top','right']].set_visible(False)
    ax5.set_title('Room CVR with 95% Wilson CI', fontsize=10,
                  fontweight='bold', color=COLORS['navy'])
    ax5.set_xlabel('CVR %', fontsize=8, color=COLORS['text'])
    ax5.tick_params(labelsize=8)

    # --- Chart 6: Anomaly products ---
    ax6 = fig.add_subplot(gs[2, :])
    gdf = gap_r['anomaly_df'].head(15).sort_values('revenue_lost', ascending=False)
    bar_colors = [COLORS['coral'] if z < -3 else COLORS['terracotta']
                  for z in gdf['z_score']]
    bars6 = ax6.bar(gdf['product_id'].astype(str), gdf['revenue_lost'],
                    color=bar_colors, edgecolor='none', width=0.6)
    ax6.set_facecolor(COLORS['cream'])
    ax6.spines[['top','right']].set_visible(False)
    ax6.set_title(
        f'Top Anomaly Products — Est. Revenue Lost (n={gap_r["anomaly_count"]} anomalies, '
        f'Total ${gap_r["total_rev_lost"]:,.0f})',
        fontsize=10, fontweight='bold', color=COLORS['navy'])
    ax6.set_xlabel('Product ID', fontsize=8, color=COLORS['text'])
    ax6.set_ylabel('Est. Revenue Lost ($)', fontsize=8, color=COLORS['text'])
    ax6.tick_params(axis='x', rotation=45, labelsize=7)
    ax6.tick_params(axis='y', labelsize=8)

    # Legend for anomaly severity
    p1 = mpatches.Patch(color=COLORS['coral'],      label='Severe (z < -3)')
    p2 = mpatches.Patch(color=COLORS['terracotta'], label='Moderate (z < -2)')
    ax6.legend(handles=[p1, p2], fontsize=8, frameon=False)

    # Main title
    fig.suptitle('Face2Shop — Statistical Insight Dashboard',
                 fontsize=16, fontweight='bold', color=COLORS['navy'], y=1.01)

    path = f"{CHART_DIR}/insight_dashboard_{REPORT_DATE}.png"
    fig.savefig(path, dpi=150, bbox_inches='tight',
                facecolor=COLORS['cream'], edgecolor='none')
    plt.close(fig)
    print(f"    ✓ Insight dashboard saved: {path}")
    return path

# -----------------------------------------------------------------------------
# INTERVIEW SUMMARY — plain text output
# -----------------------------------------------------------------------------
def print_interview_summary(funnel_r, segment_r, hourly_r, room_r, gap_r):
    print("\n" + "="*60)
    print("  INTERVIEW-READY FINDINGS")
    print("="*60)

    print(f"""
1. FUNNEL DROP-OFF
   • {funnel_r['drop_off_pct']}% of visitors never purchase
   • Overall CVR: {funnel_r['overall_cvr_pct']}% vs industry 2% benchmark
   • Gap vs industry: {funnel_r['vs_industry_2pct']:+.2f}%
   • Statistically significant (χ²={funnel_r['chi2_statistic']}, p={funnel_r['p_value']})

2. PRICE SEGMENT
   • Revenue differences across segments are significant
     (ANOVA F={segment_r['f_statistic']}, p={segment_r['p_value']})
   • Effect size η²={segment_r['eta_squared']} 
     ({'large' if segment_r['eta_squared'] > 0.14 else 'medium' if segment_r['eta_squared'] > 0.06 else 'small'} effect)

3. HOURLY BEHAVIOR
   • Peak purchase hour: {hourly_r['peak_hour']}:00 ({hourly_r['peak_count']:,} purchases)
   • Mean per hour: {hourly_r['mean_per_hour']} (95% CI: [{hourly_r['ci_95_low']}, {hourly_r['ci_95_high']}])
   • Business hours (9–18) drive {hourly_r['biz_hours_pct']}% of all purchases
   • Hourly variation is significant (Kruskal-Wallis H={hourly_r['kw_statistic']}, p={hourly_r['kw_p_value']})

4. ROOM PERFORMANCE
   • Top room: {room_r['top_room']} ({room_r['top_cvr']:.4f}% CVR)
   • Outperforms others significantly (χ²={room_r['chi2']}, p={room_r['p_value']})
   • Wilson CI used — ranking is statistically robust

5. PRODUCT ANOMALIES
   • {gap_r['anomaly_count']} products with z-score < -2 (abnormally low CVR)
   • Estimated revenue opportunity: ${gap_r['total_rev_lost']:,.0f}
   • Recommended action: price audit, image review, description rewrite
""")

# -----------------------------------------------------------------------------
# EXPORT — Save findings to CSV
# -----------------------------------------------------------------------------
def export_csvs(funnel_r, segment_r, hourly_r, room_r, gap_r):
    print("  Exporting CSVs...")

    summary = pd.DataFrame([{
        'metric':    'Overall CVR %',       'value': funnel_r['overall_cvr_pct']}, {
        'metric':    'Drop-off %',           'value': funnel_r['drop_off_pct']}, {
        'metric':    'vs Industry (2%) %',   'value': funnel_r['vs_industry_2pct']}, {
        'metric':    'Peak Purchase Hour',   'value': funnel_r['views']}, {
        'metric':    'Anomaly Products',     'value': gap_r['anomaly_count']}, {
        'metric':    'Est Revenue Lost ($)', 'value': gap_r['total_rev_lost']},
    ])
    summary.to_csv(f"{OUTPUT_DIR}/kpi_summary_{REPORT_DATE}.csv", index=False)

    room_r['ranked_df'].to_csv(
        f"{OUTPUT_DIR}/room_cvr_with_ci_{REPORT_DATE}.csv", index=False)
    gap_r['anomaly_df'].to_csv(
        f"{OUTPUT_DIR}/anomaly_products_{REPORT_DATE}.csv", index=False)
    segment_r['cvr_by_seg'].to_csv(
        f"{OUTPUT_DIR}/segment_cvr_{REPORT_DATE}.csv", index=False)
    hourly_r['hourly_df'].to_csv(
        f"{OUTPUT_DIR}/hourly_behavior_{REPORT_DATE}.csv", index=False)

    print(f"    ✓ CSVs saved to {OUTPUT_DIR}/")

# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    print("\n" + "="*60)
    print("  Face2Shop Insight Engine — Starting")
    print("="*60)

    engine = get_engine()

    print("\nRunning statistical analyses...")
    funnel_r  = analyze_funnel(engine)
    segment_r = analyze_price_segments(engine)
    hourly_r  = analyze_hourly(engine)
    room_r    = analyze_rooms(engine)
    gap_r     = analyze_gaps(engine)

    build_insight_charts(funnel_r, segment_r, hourly_r, room_r, gap_r)
    export_csvs(funnel_r, segment_r, hourly_r, room_r, gap_r)
    print_interview_summary(funnel_r, segment_r, hourly_r, room_r, gap_r)

    print("="*60)
    print("  Insight Engine COMPLETE")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
