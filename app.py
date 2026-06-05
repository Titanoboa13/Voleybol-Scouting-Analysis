"""Volleyball Scouting Karar Destek Paneli — Streamlit port of Model.ipynb.

Faithful port of the Dash dashboard. All formulas, thresholds, percentile
math, normalization, scout_score, PDF story order and colour thresholds are
preserved verbatim from the notebook.

Run:
    streamlit run app.py --server.port 8060
"""

# ── Section 1: Imports ─────────────────────────────────────────────────────
import io
from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                Paragraph, Spacer, HRFlowable)

st.set_page_config(page_title="Volleyball Scouting", layout="wide")


# ── Section 2: Constants ───────────────────────────────────────────────────
POSITION_NAMES = {
    1: 'Setter',
    2: 'Opposite Hitter',
    3: 'Middle Blocker',
    4: 'Outside Hitter',
    6: 'Libero',
}

# Distinct, high-contrast colour per position. Keyed by position_number so the
# same palette is reusable anywhere (avatars, badges, future charts). All five
# are dark enough for white/light text to stay readable on Streamlit's dark theme.
POSITION_COLORS = {
    1: '#2980b9',  # Setter          — blue
    2: '#e67e22',  # Opposite Hitter — orange
    3: '#27ae60',  # Middle Blocker  — green
    4: '#8e44ad',  # Outside Hitter  — purple
    6: '#c0392b',  # Libero          — red
}

METRICS = ['height', 'spike', 'block', 'jump_power']
METRIC_LABELS = {
    'height':     'Height (cm)',
    'spike':      'Spike Reach (cm)',
    'block':      'Block Reach (cm)',
    'jump_power': 'Jump Power (cm)',
}
METRIC_SHORT = {
    'height': 'Height', 'spike': 'Spike', 'block': 'Block', 'jump_power': 'Jump Pwr'
}

RADAR_METRICS = ['height', 'spike', 'block', 'jump_power', 'spike_percentile', 'block_percentile']
RADAR_LABELS = {
    'height':           'Height',
    'spike':            'Spike Reach',
    'block':            'Block Reach',
    'jump_power':       'Jump Power',
    'spike_percentile': 'Spike %ile',
    'block_percentile': 'Block %ile',
}
RADAR_RAW_LABELS = {
    'height':           'Height (cm)',
    'spike':            'Spike Reach (cm)',
    'block':            'Block Reach (cm)',
    'jump_power':       'Jump Power (cm)',
    'spike_percentile': 'Spike Percentile (%)',
    'block_percentile': 'Block Percentile (%)',
}

PDF_METRICS = [
    ('Height',           'height',           'cm'),
    ('Spike Reach',      'spike',            'cm'),
    ('Block Reach',      'block',            'cm'),
    ('Jump Power',       'jump_power',       'cm'),
    ('Spike Percentile', 'spike_percentile', '%'),
    ('Block Percentile', 'block_percentile', '%'),
]

_PDF_NAVY    = colors.HexColor('#2c3e50')
_PDF_CRIMSON = colors.HexColor('#7b241c')
_PDF_GREEN   = colors.HexColor('#1e8449')
_PDF_LGRAY   = colors.HexColor('#f5f5f5')
_PDF_MGRAY   = colors.HexColor('#bdc3c7')
_PDF_DGRAY   = colors.HexColor('#555555')

SAMPLE_CSV = (
    "name,position_number,height,spike,block\n"
    "Anna Müller,1,176,284,273\n"
    "Sophie Chen,2,181,288,276\n"
    "Maria Santos,3,187,295,284\n"
    "Elena Popova,4,183,281,270\n"
    "Kim Lee,6,170,268,261\n"
)

# Gemini AI commentary (Player Comparison tab only). Model string confirmed
# working via test_gemini.py. The key lives in .streamlit/secrets.toml.
GEMINI_MODEL = "gemini-2.5-flash"
_GEMINI_PLACEHOLDER = "PASTE_YOUR_KEY_HERE"


# ── Section 3: Verbatim stat / PDF helpers (no Dash dependency) ────────────
# normalize() and _pct_rank() reference the module-level globals df_clean,
# _metric_min and _metric_max, which are assigned in Section 7 before any UI
# code path (Section 8) calls them.

def _num_or_none(value):
    """Return float(value) when it is a real number, else None.

    The dataset (data/final_dataset.csv) leaves spike/block/height blank (NaN)
    for players Wikipedia doesn't cover. Every display/calculation guards on this
    so a blank renders as '—' and never poisons a percentile, benchmark, or PDF."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def _fmt_int(value, dash='—'):
    """int(value) when present, else the dash placeholder."""
    n = _num_or_none(value)
    return int(round(n)) if n is not None else dash


def normalize(value, metric):
    mn, mx = _metric_min[metric], _metric_max[metric]
    if mx == mn:
        return 50.0
    return round((value - mn) / (mx - mn) * 100, 1)


def _pct_rank(value, col):
    """Fraction of df_clean rows with col <= value, expressed as 0-100.
    Returns None when value is missing (so callers can render '—')."""
    if value is None or pd.isna(value):
        return None
    return round((df_clean[col] <= value).mean() * 100, 1)


def _player_metric_table(row):
    data = [['Metric', 'Value', 'Percentile Rank']]
    for label, col, unit in PDF_METRICS:
        val = _num_or_none(row[col])
        if val is None:
            data.append([label, '—', '—'])
            continue
        pct = _pct_rank(val, col)
        data.append([label, f"{val:.1f} {unit}",
                     f"{pct}%" if pct is not None else '—'])
    t = Table(data, colWidths=[7*cm, 5*cm, 6*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND',     (0, 0), (-1,  0), _PDF_NAVY),
        ('TEXTCOLOR',      (0, 0), (-1,  0), colors.white),
        ('FONTNAME',       (0, 0), (-1,  0), 'Helvetica-Bold'),
        ('FONTSIZE',       (0, 0), (-1,  0), 10),
        ('ALIGN',          (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN',          (0, 1), ( 0, -1), 'LEFT'),
        ('FONTSIZE',       (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, _PDF_LGRAY]),
        ('GRID',           (0, 0), (-1, -1), 0.4, _PDF_MGRAY),
        ('TOPPADDING',     (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 5),
        ('LEFTPADDING',    (0, 0), (-1, -1), 7),
    ]))
    return t


def _h2h_comparison_table(row1, row2, p1_name, p2_name):
    p1s = p1_name.split()[0]
    p2s = p2_name.split()[0]
    data = [['Metric', p1s, p2s, 'Edge']]
    win_style = []

    for i, (label, col, unit) in enumerate(PDF_METRICS, start=1):
        v1, v2 = _num_or_none(row1[col]), _num_or_none(row2[col])
        s1 = f"{v1:.1f} {unit}" if v1 is not None else '—'
        s2 = f"{v2:.1f} {unit}" if v2 is not None else '—'
        if v1 is None or v2 is None:
            edge = '—'                      # can't compare when a stat is missing
        elif v1 > v2:
            edge = f'{p1s} ▲'
            win_style += [
                ('BACKGROUND', (1, i), (1, i), _PDF_GREEN),
                ('TEXTCOLOR',  (1, i), (1, i), colors.white),
                ('FONTNAME',   (1, i), (1, i), 'Helvetica-Bold'),
            ]
        elif v2 > v1:
            edge = f'{p2s} ▲'
            win_style += [
                ('BACKGROUND', (2, i), (2, i), _PDF_GREEN),
                ('TEXTCOLOR',  (2, i), (2, i), colors.white),
                ('FONTNAME',   (2, i), (2, i), 'Helvetica-Bold'),
            ]
        else:
            edge = 'Tie'
        data.append([label, s1, s2, edge])

    t = Table(data, colWidths=[5.5*cm, 4*cm, 4*cm, 4.5*cm])
    base_style = [
        ('BACKGROUND',     (0,  0), (-1,  0), _PDF_NAVY),
        ('TEXTCOLOR',      (0,  0), (-1,  0), colors.white),
        ('FONTNAME',       (0,  0), (-1,  0), 'Helvetica-Bold'),
        ('FONTSIZE',       (0,  0), (-1,  0), 10),
        ('ALIGN',          (0,  0), (-1, -1), 'CENTER'),
        ('ALIGN',          (0,  1), ( 0, -1), 'LEFT'),
        ('FONTSIZE',       (0,  1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0,  1), (-1, -1), [colors.white, _PDF_LGRAY]),
        ('GRID',           (0,  0), (-1, -1), 0.4, _PDF_MGRAY),
        ('TOPPADDING',     (0,  0), (-1, -1), 5),
        ('BOTTOMPADDING',  (0,  0), (-1, -1), 5),
        ('LEFTPADDING',    (0,  0), (-1, -1), 7),
    ]
    t.setStyle(TableStyle(base_style + win_style))
    return t


def _build_recommendation(row1, row2, p1_name, p2_name):
    p1_pos = POSITION_NAMES.get(int(row1['position_number']), 'Unknown')
    p2_pos = POSITION_NAMES.get(int(row2['position_number']), 'Unknown')

    # Only metrics both players actually have are comparable.
    p1_leads, p2_leads, ties = [], [], 0
    for label, col, _ in PDF_METRICS:
        v1, v2 = _num_or_none(row1[col]), _num_or_none(row2[col])
        if v1 is None or v2 is None:
            continue
        if v1 > v2:
            p1_leads.append(label)
        elif v2 > v1:
            p2_leads.append(label)
        else:
            ties += 1

    p1_wins, p2_wins = len(p1_leads), len(p2_leads)
    total = p1_wins + p2_wins + ties

    if total == 0:
        return (
            f"Insufficient comparable statistics between {p1_name} ({p1_pos}) and "
            f"{p2_name} ({p2_pos}) — one or both players are missing the measured "
            f"attributes (spike/block reach), so no head-to-head recommendation can "
            f"be made on physical metrics alone."
        )

    if p1_wins > p2_wins:
        stronger, weaker   = p1_name, p2_name
        stronger_pos       = p1_pos
        s_wins             = p1_wins
        s_metrics, w_metrics = p1_leads, p2_leads
    elif p2_wins > p1_wins:
        stronger, weaker   = p2_name, p1_name
        stronger_pos       = p2_pos
        s_wins             = p2_wins
        s_metrics, w_metrics = p2_leads, p1_leads
    else:
        # Spike tiebreaker (a missing spike loses the tiebreak)
        _s1 = _num_or_none(row1['spike'])
        _s2 = _num_or_none(row2['spike'])
        if (_s1 if _s1 is not None else -1) >= (_s2 if _s2 is not None else -1):
            stronger, weaker   = p1_name, p2_name
            stronger_pos       = p1_pos
            s_metrics, w_metrics = p1_leads, p2_leads
        else:
            stronger, weaker   = p2_name, p1_name
            stronger_pos       = p2_pos
            s_metrics, w_metrics = p2_leads, p1_leads
        s_wins = p1_wins

    if p1_wins == p2_wins:
        intro = (
            f"The comparison between {p1_name} ({p1_pos}) and {p2_name} ({p2_pos}) "
            f"is evenly matched — each player leads in {p1_wins} of {total} categories, "
            f"with {stronger} earning a narrow edge on spike reach as the tiebreaker."
        )
    else:
        intro = (
            f"{stronger} ({stronger_pos}) holds a clear overall advantage, "
            f"leading in {s_wins} of {total} measured categories."
        )

    detail = ''
    if s_metrics:
        detail += f" {stronger} excels in: {', '.join(s_metrics)}."
    if w_metrics:
        detail += f" {weaker} counters with an edge in: {', '.join(w_metrics)}."

    # Jump power note (meaningful if gap ≥ 8 cm; skip when either is missing)
    jp1, jp2 = _num_or_none(row1['jump_power']), _num_or_none(row2['jump_power'])
    jp_note = ''
    if jp1 is not None and jp2 is not None and abs(jp1 - jp2) >= 8:
        jp_winner = p1_name if jp1 > jp2 else p2_name
        jp_note = (
            f" A jump-power differential of {abs(jp1 - jp2):.0f} cm in favour of "
            f"{jp_winner} signals superior explosive ability at the net."
        )

    # Spike percentile note (meaningful if gap ≥ 10 pp; skip when either missing)
    sp1, sp2 = _num_or_none(row1['spike_percentile']), _num_or_none(row2['spike_percentile'])
    sp_note = ''
    if sp1 is not None and sp2 is not None and abs(sp1 - sp2) >= 10:
        sp_winner = p1_name if sp1 > sp2 else p2_name
        top_pct   = round(100 - max(sp1, sp2), 0)
        sp_note   = (
            f" {sp_winner}'s spike reach places them in the top {top_pct:.0f}% "
            f"of all scouted athletes — an elite attacking asset."
        )

    closing = (
        " Recommendation: weigh positional need and tactical system fit "
        "alongside these metrics before finalising any recruitment decision."
    )

    return intro + detail + jp_note + sp_note + closing


def generate_scouting_pdf(player1_name, player2_name):
    row1  = df_clean[df_clean['name'] == player1_name].iloc[0]
    row2  = df_clean[df_clean['name'] == player2_name].iloc[0]
    p1_pos = POSITION_NAMES.get(int(row1['position_number']), 'Unknown')
    p2_pos = POSITION_NAMES.get(int(row2['position_number']), 'Unknown')

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm,  bottomMargin=1.5*cm,
    )

    styles  = getSampleStyleSheet()
    sub_style = ParagraphStyle(
        'Sub', parent=styles['Normal'],
        fontSize=9, textColor=colors.grey, spaceAfter=2,
    )
    sec_style = ParagraphStyle(
        'Sec', parent=styles['Normal'],
        fontSize=13, textColor=_PDF_NAVY, fontName='Helvetica-Bold',
        spaceBefore=12, spaceAfter=5,
    )
    body_style = ParagraphStyle(
        'Body', parent=styles['Normal'],
        fontSize=9.5, leading=14, textColor=_PDF_DGRAY,
    )
    pos_style = ParagraphStyle(
        'Pos', parent=styles['Normal'],
        fontSize=10, textColor=_PDF_DGRAY, spaceAfter=4,
    )

    story = []

    # ── Header ───────────────────────────────────────────────────────────
    hdr = Table(
        [['Volleyball Scouting Report', 'CONFIDENTIAL']],
        colWidths=[12*cm, 6*cm],
    )
    hdr.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (0, 0), _PDF_NAVY),
        ('BACKGROUND',    (1, 0), (1, 0), _PDF_CRIMSON),
        ('TEXTCOLOR',     (0, 0), (-1, 0), colors.white),
        ('FONTNAME',      (0, 0), (0, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (0, 0), 18),
        ('FONTNAME',      (1, 0), (1, 0), 'Helvetica-Bold'),
        ('FONTSIZE',      (1, 0), (1, 0), 11),
        ('ALIGN',         (0, 0), (0, 0), 'LEFT'),
        ('ALIGN',         (1, 0), (1, 0), 'RIGHT'),
        ('VALIGN',        (0, 0), (-1, 0), 'MIDDLE'),
        ('TOPPADDING',    (0, 0), (-1, 0), 14),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 14),
        ('LEFTPADDING',   (0, 0), (0, 0), 12),
        ('RIGHTPADDING',  (1, 0), (1, 0), 12),
    ]))
    story.append(hdr)
    story.append(Spacer(1, 0.15*cm))
    story.append(Paragraph(
        f"Generated: {date.today().strftime('%d %B %Y')}  ·  Internal Use Only",
        sub_style,
    ))
    story.append(HRFlowable(width='100%', thickness=1.5, color=_PDF_NAVY, spaceAfter=8))

    # ── Player 1 ─────────────────────────────────────────────────────────
    story.append(Paragraph(f"Player 1: {player1_name}", sec_style))
    story.append(Paragraph(f"Position: {p1_pos}", pos_style))
    story.append(_player_metric_table(row1))

    story.append(Spacer(1, 0.5*cm))

    # ── Player 2 ─────────────────────────────────────────────────────────
    story.append(Paragraph(f"Player 2: {player2_name}", sec_style))
    story.append(Paragraph(f"Position: {p2_pos}", pos_style))
    story.append(_player_metric_table(row2))

    story.append(Spacer(1, 0.5*cm))

    # ── Head-to-Head ─────────────────────────────────────────────────────
    story.append(Paragraph("Head-to-Head Comparison", sec_style))
    story.append(Paragraph(
        "Green cells indicate the higher value for each metric.",
        ParagraphStyle('note', parent=styles['Normal'],
                       fontSize=8, textColor=colors.grey, spaceAfter=4),
    ))
    story.append(_h2h_comparison_table(row1, row2, player1_name, player2_name))

    story.append(Spacer(1, 0.5*cm))

    # ── Scout Recommendation ─────────────────────────────────────────────
    story.append(Paragraph("Scout Recommendation", sec_style))
    story.append(HRFlowable(width='100%', thickness=0.5, color=_PDF_MGRAY, spaceAfter=6))
    rec_text = _build_recommendation(row1, row2, player1_name, player2_name)
    story.append(Paragraph(rec_text, body_style))

    doc.build(story)
    buf.seek(0)
    return buf.read()


# ── Section 4: Team-analysis helpers ───────────────────────────────────────
def parse_uploaded_csv(uploaded_file):
    """Validate and prepare an uploaded team roster. Mirrors the notebook's
    parse_csv validation (required columns, numeric coercion, dropna)."""
    try:
        team_df = pd.read_csv(uploaded_file)
    except Exception as exc:
        return None, f"Could not parse file: {exc}"
    required = {'name', 'position_number', 'height', 'spike', 'block'}
    missing  = required - set(team_df.columns)
    if missing:
        return None, f"Missing columns: {', '.join(sorted(missing))}"
    team_df = team_df[list(required)].copy()
    team_df['position_number'] = pd.to_numeric(team_df['position_number'], errors='coerce')
    for col in ['height', 'spike', 'block']:
        team_df[col] = pd.to_numeric(team_df[col], errors='coerce')
    team_df = team_df.dropna().reset_index(drop=True)
    if team_df.empty:
        return None, "No valid rows found after parsing."
    team_df['jump_power']    = team_df['spike'] - team_df['height']
    team_df['position_name'] = team_df['position_number'].map(POSITION_NAMES).fillna('Unknown')
    return team_df, None


def build_squad_chart(team_df):
    counts  = team_df.groupby('position_number').size().reset_index(name='count')
    all_pos = pd.DataFrame({
        'position_number': list(POSITION_NAMES.keys()),
        'position_name':   list(POSITION_NAMES.values()),
    })
    counts  = all_pos.merge(counts, on='position_number', how='left').fillna(0)
    counts['count'] = counts['count'].astype(int)
    colors_ = ['#e74c3c' if n == 0 else '#5b8db8' for n in counts['count']]
    fig = go.Figure(go.Bar(
        x=counts['position_name'], y=counts['count'],
        marker_color=colors_, text=counts['count'], textposition='outside',
    ))
    fig.update_layout(
        title='Players per Position  (red = missing)',
        xaxis_title='Position', yaxis_title='Number of Players',
        yaxis=dict(dtick=1, gridcolor='#eeeeee', rangemode='tozero'),
        plot_bgcolor='white', font=dict(family='Arial'), showlegend=False,
    )
    return fig


def compute_weakness(team_df):
    """Returns (weakness_rows, below_cells, score_rows) — verbatim logic from
    the notebook's build_weakness_section."""
    compare_metrics = ['height', 'spike', 'block', 'jump_power']
    rows, below_cells = [], []
    for i, (_, player) in enumerate(team_df.iterrows()):
        pos_num = int(player['position_number'])
        avgs    = benchmark_avgs.get(pos_num, {})
        row     = {'name': player['name'], 'position': POSITION_NAMES.get(pos_num, 'Unknown')}
        for m in compare_metrics:
            val = round(float(player[m]), 1)
            row[m] = val
            if avgs and val < avgs.get(m, val + 1):
                below_cells.append((i, m))
        rows.append(row)

    score_rows = []
    for pos_num, pos_name in POSITION_NAMES.items():
        pos_players = team_df[team_df['position_number'] == pos_num]
        avgs        = benchmark_avgs.get(pos_num, {})
        if pos_players.empty or not avgs:
            score_rows.append({'position': pos_name, 'players': 0,
                               'score': None, 'status': 'Missing', 'color': '#e74c3c'})
            continue
        scores = [(pos_players[m].mean() / avgs[m]) * 100 for m in ['height', 'spike', 'block']]
        score  = round(sum(scores) / len(scores), 1)
        if score >= 97:   status, color = 'Strong',  '#27ae60'
        elif score >= 90: status, color = 'Average', '#f39c12'
        else:             status, color = 'Weak',    '#e74c3c'
        score_rows.append({'position': pos_name, 'players': len(pos_players),
                           'score': score, 'status': status, 'color': color})
    return rows, below_cells, score_rows


def build_transfer_targets(score_rows):
    """For each weak/missing position, return (target, candidate_rows). Verbatim
    logic from the notebook's build_transfer_section."""
    targets = [r for r in score_rows if r['status'] in ('Weak', 'Missing')]
    sections = []
    for r in targets:
        pos_num    = next(k for k, v in POSITION_NAMES.items() if v == r['position'])
        candidates = (df_clean[df_clean['position_number'] == pos_num]
                      .sort_values('scout_score', ascending=False).head(5))
        subtitle   = '(missing)' if r['status'] == 'Missing' else f"(score: {r['score']}%)"
        rec_rows   = [
            {
                'Name':       row['name'],
                'Country':    row['country'] if pd.notna(row['country']) else '?',
                'Height (cm)': _fmt_int(row['height']),
                'Spike (cm)':  _fmt_int(row['spike']),
                'Block (cm)':  _fmt_int(row['block']),
                'Jump Power':  _fmt_int(row['jump_power']),
                'Spike %ile':  round(row['spike_percentile'], 1)
                               if pd.notna(row['spike_percentile']) else '—',
            }
            for _, row in candidates.iterrows()
        ]
        sections.append((r, subtitle, rec_rows))
    return sections


# ── Section 5: Plot builders ───────────────────────────────────────────────
def build_scout_figure(min_spike, max_height):
    filtered = df_clean[
        (df_clean['spike'] >= min_spike) & (df_clean['height'] <= max_height)
    ]
    fig = px.scatter(
        filtered, x='height', y='spike',
        hover_name='name', color='jump_power', size='jump_power',
        color_continuous_scale='Viridis',
        labels={'height': 'Boy (cm)', 'spike': 'Smaç Yüksekliği (cm)', 'jump_power': 'Zıplama Gücü'},
        title=f"Kriterlere Uygun {len(filtered)} Oyuncu Bulundu",
    )
    fig.update_layout(transition_duration=500)
    return fig


def build_benchmark_figure(metric):
    label     = METRIC_LABELS[metric]
    positions = benchmark_df['Position'].tolist()
    fig = go.Figure([
        go.Bar(name='Average',   x=positions, y=benchmark_df[f'{metric}_avg'],
               marker_color='#5b8db8', text=benchmark_df[f'{metric}_avg'],   textposition='outside'),
        go.Bar(name='Top 25%',   x=positions, y=benchmark_df[f'{metric}_top25'],
               marker_color='#f39c12', text=benchmark_df[f'{metric}_top25'], textposition='outside'),
        go.Bar(name='Elite 10%', x=positions, y=benchmark_df[f'{metric}_elite'],
               marker_color='#e74c3c', text=benchmark_df[f'{metric}_elite'], textposition='outside'),
    ])
    fig.update_layout(
        barmode='group', title=f'{label} — Benchmarks by Position',
        xaxis_title='Position', yaxis_title=label, legend_title='Benchmark Level',
        font={'family': 'Arial'}, plot_bgcolor='white',
        yaxis=dict(gridcolor='#eeeeee'),
        uniformtext_minsize=8, uniformtext_mode='hide',
    )
    return fig


def build_comparison(player1, player2):
    row1 = df_clean[df_clean['name'] == player1].iloc[0]
    row2 = df_clean[df_clean['name'] == player2].iloc[0]

    # Only plot axes where BOTH players have a value — a missing stat would
    # otherwise distort or break the polygon. Dropped axes are reported back so
    # the UI can tell the user which were omitted.
    common = [m for m in RADAR_METRICS
              if _num_or_none(row1[m]) is not None and _num_or_none(row2[m]) is not None]
    dropped = [m for m in RADAR_METRICS if m not in common]
    note = None
    if dropped:
        note = ("Radar axes omitted (missing data for one or both players): "
                + ", ".join(RADAR_LABELS[m] for m in dropped) + ".")

    fig = go.Figure()
    if len(common) >= 3:
        categories  = [RADAR_LABELS[m] for m in common]
        cats_closed = categories + [categories[0]]
        p1_norm = [normalize(row1[m], m) for m in common]
        p2_norm = [normalize(row2[m], m) for m in common]
        fig.add_trace(go.Scatterpolar(
            r=p1_norm + [p1_norm[0]], theta=cats_closed, fill='toself', name=player1,
            line=dict(color='#2980b9', width=2), fillcolor='rgba(41,128,185,0.2)',
        ))
        fig.add_trace(go.Scatterpolar(
            r=p2_norm + [p2_norm[0]], theta=cats_closed, fill='toself', name=player2,
            line=dict(color='#e74c3c', width=2), fillcolor='rgba(231,76,60,0.2)',
        ))
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(size=9))),
            showlegend=True, legend=dict(font=dict(family='Arial')),
            title=dict(text=f"{player1}  vs  {player2}",
                       font=dict(family='Arial', color='#2c3e50')),
            font=dict(family='Arial'),
        )
    else:
        fig.add_annotation(
            text=("Not enough shared metrics to draw a radar "
                  "(need at least 3 that both players have)."),
            showarrow=False, font=dict(family='Arial', size=14, color='#7b241c'),
        )
        fig.update_layout(
            title=dict(text=f"{player1}  vs  {player2}",
                       font=dict(family='Arial', color='#2c3e50')),
            xaxis=dict(visible=False), yaxis=dict(visible=False),
            font=dict(family='Arial'),
        )

    pos1 = POSITION_NAMES.get(int(row1['position_number']), '?')
    pos2 = POSITION_NAMES.get(int(row2['position_number']), '?')
    table_rows = [{'Metric': 'Position', player1: pos1, player2: pos2}]
    for m in RADAR_METRICS:
        v1, v2 = _num_or_none(row1[m]), _num_or_none(row2[m])
        table_rows.append({
            'Metric': RADAR_RAW_LABELS[m],
            player1: str(round(v1, 1)) if v1 is not None else '—',
            player2: str(round(v2, 1)) if v2 is not None else '—',
        })
    table_df = pd.DataFrame(table_rows)
    return fig, table_df, note


# ── Section 5b: Gemini AI commentary (Player Comparison tab) ───────────────
def _get_gemini_key():
    """Return a usable Gemini key from st.secrets, or None if it is missing or
    still the placeholder. Never raises — a missing secrets file is fine."""
    try:
        key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None
    key = (key or "").strip()
    if not key or key == _GEMINI_PLACEHOLDER:
        return None
    return key


@st.cache_data(show_spinner=False)
def generate_ai_commentary(player1_name, player2_name, language):
    """Short Gemini scouting note comparing two players, in the chosen language.

    Cached on (player1_name, player2_name, language) so each unique combination
    triggers at most one API call; repeats return the cached text for free.
    Returns the commentary text. Raises on API failure so the caller can show a
    warning AND so transient failures are not cached (they can be retried)."""
    key = _get_gemini_key()
    if not key:
        # Caller checks the key first, so this is just a safety guard.
        raise RuntimeError("Gemini key not configured")

    row1 = df_clean[df_clean['name'] == player1_name].iloc[0]
    row2 = df_clean[df_clean['name'] == player2_name].iloc[0]

    _fields = [
        ('height', 'height', 'cm'), ('spike', 'spike reach', 'cm'),
        ('block', 'block reach', 'cm'), ('jump_power', 'jump power', 'cm'),
        ('spike_percentile', 'spike percentile', ''),
        ('block_percentile', 'block percentile', ''),
    ]

    def _stat_block(name, row):
        pos = POSITION_NAMES.get(int(row['position_number']), 'Unknown')
        available, missing = [], []
        for col, label, unit in _fields:
            v = _num_or_none(row[col])
            if v is None:
                missing.append(label)
            else:
                available.append(f"{label}={v:.0f}{(' ' + unit) if unit else ''}")
        line = f"{name} (position: {pos}): " + ", ".join(available)
        if missing:
            line += (f". UNAVAILABLE (do not infer, estimate, or comment on these): "
                     f"{', '.join(missing)}")
        return line

    lang_line = ("Write the note in Turkish." if language == "Türkçe"
                 else "Write the note in English.")

    prompt = (
        "You are a volleyball scout writing a brief head-to-head note comparing "
        "two players. Base your comparison ONLY on the statistics provided below. "
        "Some stats may be marked UNAVAILABLE — never invent, estimate, or comment "
        "on those; compare only on the stats that are present. "
        "Do NOT invent any biographical details — no career history, teams, ages, "
        "nationalities, or achievements that are not in the data. "
        "Write 2-4 sentences maximum in a concise scouting tone, and state clearly "
        "which player has the edge and in which attributes.\n\n"
        f"{_stat_block(player1_name, row1)}\n"
        f"{_stat_block(player2_name, row2)}\n\n"
        f"{lang_line}"
    )

    from google import genai
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    text = (resp.text or "").strip()
    if not text:
        raise ValueError("Gemini returned an empty response")
    return text


# ── Section 5c: Player Profile helpers (avatar, age, detailed AI profile) ──
def _compute_age(dob):
    """Integer age as of today from a parsed date/Timestamp, or None when the
    value is missing/unparseable (NaT). Never raises."""
    if dob is None or pd.isna(dob):
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _initials(name):
    """First letter of the first and last name parts (max 2), uppercased."""
    parts = [p for p in str(name).split() if p]
    if not parts:
        return "?"
    letters = parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")
    return letters.upper()


def _avatar_html(name, position_number, size=96):
    """Circular initials avatar coloured by position, white text for contrast.
    Rendered via st.markdown(unsafe_allow_html=True)."""
    color = POSITION_COLORS.get(int(position_number), '#555555')
    return (
        f"<div style='width:{size}px;height:{size}px;border-radius:50%;"
        f"background-color:{color};display:flex;align-items:center;"
        f"justify-content:center;color:#ffffff;font-family:Arial;"
        f"font-size:{int(size * 0.4)}px;font-weight:bold;letter-spacing:1px;"
        f"box-shadow:0 2px 6px rgba(0,0,0,0.35);'>{_initials(name)}</div>"
    )


@st.cache_data(show_spinner=False)
def generate_player_profile(player_name, language):
    """Detailed Gemini scouting profile for a single player in the chosen
    language. Cached on (player_name, language) so each combination triggers at
    most one API call. Feeds Gemini ONLY real numeric stats plus how the player
    compares to their position benchmark averages. Raises on failure so the
    caller can warn and so transient errors are not cached."""
    key = _get_gemini_key()
    if not key:
        raise RuntimeError("Gemini key not configured")

    row     = df_clean[df_clean['name'] == player_name].iloc[0]
    pos_num = int(row['position_number'])
    pos     = POSITION_NAMES.get(pos_num, 'Unknown')
    avgs    = benchmark_avgs.get(pos_num, {})
    age     = _compute_age(row.get('dob'))
    age_str = f"{age} years" if age is not None else "unknown"

    stat_lines = [f"Position: {pos}", f"Age: {age_str}"]
    missing_stats = []
    _profile_fields = [
        ('height', 'Height', 'cm'), ('spike', 'Spike reach', 'cm'),
        ('block', 'Block reach', 'cm'), ('jump_power', 'Jump power', 'cm'),
        ('spike_percentile', 'Spike percentile', ''),
        ('block_percentile', 'Block percentile', ''),
    ]
    for col, label, unit in _profile_fields:
        v = _num_or_none(row[col])
        if v is None:
            missing_stats.append(label)
        else:
            stat_lines.append(f"{label}: {v:.0f}{(' ' + unit) if unit else ''}")
    if missing_stats:
        stat_lines.append("UNAVAILABLE (do not infer, estimate, or comment on "
                          f"these): {', '.join(missing_stats)}")

    bench_lines = []
    for m in ['height', 'spike', 'block', 'jump_power']:
        val = _num_or_none(row[m])
        if m in avgs and val is not None:
            diff = val - avgs[m]
            sign = "above" if diff >= 0 else "below"
            bench_lines.append(
                f"{METRIC_SHORT[m]}: {val:.0f} cm "
                f"({abs(diff):.0f} cm {sign} the {pos} average of {avgs[m]:.0f} cm)"
            )

    lang_line = ("Write the profile in Turkish." if language == "Türkçe"
                 else "Write the profile in English.")

    prompt = (
        "You are an expert volleyball scout writing a DETAILED scouting profile "
        "for a single player. Base everything ONLY on the statistics provided "
        "below. Some stats may be marked UNAVAILABLE — never invent, estimate, or "
        "comment on those; build the profile only from the stats that are present. "
        "Invent NO biographical facts — no teams, clubs, achievements, "
        "career history, nationality, or personal details that are not in the "
        "data. You MAY interpret the numbers (for example, an elite block "
        "percentile suggests strong net defense), but never fabricate facts.\n\n"
        "Structure the profile in three clearly separated paragraphs with these "
        "headings:\n"
        "1. Strengths\n"
        "2. Weaknesses / areas to watch\n"
        "3. Overall assessment\n\n"
        "PLAYER STATISTICS:\n" + "\n".join(stat_lines) + "\n\n"
        f"COMPARISON TO {pos.upper()} POSITION BENCHMARK AVERAGES:\n"
        + ("\n".join(bench_lines) if bench_lines
           else "No benchmark available for this position.")
        + "\n\n" + lang_line
    )

    from google import genai
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    text = (resp.text or "").strip()
    if not text:
        raise ValueError("Gemini returned an empty response")
    return text


# ── Section 5d: Team vs Team helpers (additive — own tab) ──────────────────
# Two teams are compared position-by-position. Each team is either an uploaded
# roster (reusing parse_uploaded_csv) or built from the database filtered to one
# country. All per-position averages use pandas' default skipna so the ~10
# players with blank spike/block are excluded per-metric rather than crashing.

# Sample roster fixtures (also written to data/sample_team_*.csv, git-ignored).
# Exposed via download buttons so the CSV-upload mode can be tested immediately.
SAMPLE_TEAM_TR = (
    "name,position_number,height,spike,block\n"
    "Cansu Özbay,1,182,285,284\n"
    "Melissa Vargas,2,195,326,315\n"
    "Zehra Güneş,3,198,320,310\n"
    "Eda Erdem,3,188,315,302\n"
    "Ebrar Karakurt,4,193,315,304\n"
    "İlkin Aydın,4,183,299,298\n"
    "Gizem Örge,6,170,270,260\n"
)
SAMPLE_TEAM_IT = (
    "name,position_number,height,spike,block\n"
    "Alessia Orro,1,178,304,285\n"
    "Paola Egonu,2,195,344,321\n"
    "Anna Danesi,3,198,315,306\n"
    "Sarah Fahr,3,192,322,306\n"
    "Myriam Sylla,4,184,320,315\n"
    "Monica De Gennaro,6,174,298,215\n"
)
SAMPLE_TEAM_PL = (
    "name,position_number,height,spike,block\n"
    "Joanna Wołosz,1,181,303,281\n"
    "Malwina Smarzek,2,191,318,292\n"
    "Klaudia Alagierska,3,190,297,290\n"
    "Martyna Łukasik,4,189,315,288\n"
    "Natalia Mędrzyk,4,185,293,282\n"
    "Maria Stenzel,6,168,278,262\n"
)

# Two distinct team colours (A = blue, B = red), reused in the table + chart.
_TVT_COLOR_A = '#2980b9'
_TVT_COLOR_B = '#e74c3c'

# 5-1 system lineup: (position_number, number of slots). Total = 7 players.
# Used ONLY by "Build from database" mode to enforce a realistic roster shape.
TVT_LINEUP = [(1, 1), (2, 1), (3, 2), (4, 2), (6, 1)]
TVT_LINEUP_SIZE = sum(n for _, n in TVT_LINEUP)

_TVT_TABLE_STYLES = [
    {'selector': 'table', 'props': [('width', '100%'), ('border-collapse', 'collapse')]},
    {'selector': 'th', 'props': [
        ('background-color', '#2c3e50'), ('color', 'white'),
        ('padding', '8px 12px'), ('text-align', 'center'),
        ('font-family', 'Arial'), ('font-size', '12px'), ('font-weight', 'bold'),
    ]},
    {'selector': 'td', 'props': [
        ('color', '#e0e0e0'), ('padding', '8px 12px'), ('text-align', 'center'),
        ('font-family', 'Arial'), ('font-size', '13px'),
        ('border-bottom', '1px solid #3a3a3a'),
    ]},
]


def _team_from_db(player_names):
    """Build a team roster DataFrame from selected database players. The needed
    columns (jump_power, position_name) already exist on df_clean."""
    sub = df_clean[df_clean['name'].isin(player_names)][
        ['name', 'position_number', 'height', 'spike', 'block',
         'jump_power', 'position_name']
    ].copy()
    return sub.reset_index(drop=True)


def _team_position_stats(team_df):
    """Per-position averages for every position. Returns
    {pos_num: {'count': n, 'metrics': {metric: float|None}}}.
    A metric average is None when the position is empty OR every player in it is
    missing that stat (mean of an all-NaN slice is NaN → None)."""
    stats = {}
    for pos_num in POSITION_NAMES:
        pos_players = team_df[team_df['position_number'] == pos_num]
        count = len(pos_players)
        metrics = {}
        for m in METRICS:
            if count == 0:
                metrics[m] = None
            else:
                val = pos_players[m].mean()          # skipna default
                metrics[m] = None if pd.isna(val) else round(float(val), 1)
        stats[pos_num] = {'count': count, 'metrics': metrics}
    return stats


def _position_metric_winner(va, vb):
    """'A', 'B', or None (None when either value is missing or they tie)."""
    if va is None or vb is None:
        return None
    if va > vb:
        return 'A'
    if vb > va:
        return 'B'
    return None


def build_tvt_table(stats_a, stats_b, label_a, label_b):
    """Long-format position×metric comparison table. Returns (DataFrame,
    highlights) where highlights[i] is 'A'/'B'/None marking which side's cell to
    shade green for row i."""
    rows, highlights = [], []
    for pos_num, pos_name in POSITION_NAMES.items():
        ma = stats_a[pos_num]['metrics']
        mb = stats_b[pos_num]['metrics']
        for m in METRICS:
            va, vb = ma[m], mb[m]
            a_str = f"{va:.1f}" if va is not None else "—"
            b_str = f"{vb:.1f}" if vb is not None else "—"
            win = _position_metric_winner(va, vb)
            if va is None or vb is None:
                edge = "—"
            elif win == 'A':
                edge = f"{label_a} ▲"
            elif win == 'B':
                edge = f"{label_b} ▲"
            else:
                edge = "Even"
            rows.append({'Position': pos_name, 'Metric': METRIC_SHORT[m],
                         label_a: a_str, label_b: b_str, 'Edge': edge})
            highlights.append(win)
    return pd.DataFrame(rows), highlights


def _tvt_table_html(stats_a, stats_b, label_a, label_b):
    """Render build_tvt_table as highlighted HTML (Styler.apply inline styles
    survive to_html, so they aren't overridden like st.dataframe would)."""
    df, highlights = build_tvt_table(stats_a, stats_b, label_a, label_b)
    # Light green background WITH dark bold text so the value stays readable —
    # same dark-theme-vs-light-highlight fix as the benchmark/weakness tables.
    # !important guards against Streamlit's dark-theme td color rule.
    win_css = ('background-color:#e8f5e9 !important;color:#1a1a1a !important;'
               'font-weight:bold;')

    def _shade(_):
        css = pd.DataFrame('', index=df.index, columns=df.columns)
        for i, win in enumerate(highlights):
            if win == 'A':
                css.loc[i, label_a] = win_css
            elif win == 'B':
                css.loc[i, label_b] = win_css
        return css

    styler = (df.style
        .apply(_shade, axis=None)
        .hide(axis='index')
        .set_table_styles(_TVT_TABLE_STYLES))
    return styler.to_html()


def build_tvt_position_chart(stats_a, stats_b, label_a, label_b, metric):
    """Grouped bar chart of one metric's per-position averages, Team A vs B."""
    positions = [POSITION_NAMES[p] for p in POSITION_NAMES]
    ya = [stats_a[p]['metrics'][metric] for p in POSITION_NAMES]
    yb = [stats_b[p]['metrics'][metric] for p in POSITION_NAMES]
    fig = go.Figure([
        go.Bar(name=label_a, x=positions, y=ya, marker_color=_TVT_COLOR_A,
               text=[f"{v:.0f}" if v is not None else "" for v in ya],
               textposition='outside'),
        go.Bar(name=label_b, x=positions, y=yb, marker_color=_TVT_COLOR_B,
               text=[f"{v:.0f}" if v is not None else "" for v in yb],
               textposition='outside'),
    ])
    fig.update_layout(
        barmode='group', title=f'{METRIC_LABELS[metric]} — Average by Position',
        xaxis_title='Position', yaxis_title=METRIC_LABELS[metric],
        legend_title='Team', font={'family': 'Arial'}, plot_bgcolor='white',
        yaxis=dict(gridcolor='#eeeeee', rangemode='tozero'),
        uniformtext_minsize=8, uniformtext_mode='hide',
    )
    return fig


def tvt_summary_and_warnings(stats_a, stats_b, label_a, label_b):
    """Strengths/weaknesses + tactical warnings. Returns
    (a_advantage, b_advantage, even, warnings) — first three are position-name
    lists, the last a list of warning strings."""
    a_adv, b_adv, even, warnings = [], [], [], []
    for pos_num, pos_name in POSITION_NAMES.items():
        ca = stats_a[pos_num]['count']
        cb = stats_b[pos_num]['count']
        if ca == 0 and cb == 0:
            warnings.append(f"Neither team fields a {pos_name}.")
            continue
        if ca == 0:
            warnings.append(f"{label_a} has no {pos_name} — {label_b} is unopposed here.")
            b_adv.append(pos_name)
            continue
        if cb == 0:
            warnings.append(f"{label_b} has no {pos_name} — {label_a} is unopposed here.")
            a_adv.append(pos_name)
            continue
        a_wins = b_wins = comparable = 0
        for m in METRICS:
            win = _position_metric_winner(stats_a[pos_num]['metrics'][m],
                                          stats_b[pos_num]['metrics'][m])
            if win is None:
                continue
            comparable += 1
            if win == 'A':
                a_wins += 1
            else:
                b_wins += 1
        if a_wins > b_wins:
            a_adv.append(pos_name)
        elif b_wins > a_wins:
            b_adv.append(pos_name)
        else:
            even.append(pos_name)
        # Clear mismatch: one side leads every comparable metric (≥3 of 4).
        if comparable >= 3 and a_wins == comparable:
            warnings.append(f"{label_b} is weak at {pos_name} — "
                            f"{label_a} leads every measured metric.")
        elif comparable >= 3 and b_wins == comparable:
            warnings.append(f"{label_a} is weak at {pos_name} — "
                            f"{label_b} leads every measured metric.")
    return a_adv, b_adv, even, warnings


def _tvt_gemini_summary(stats_a, stats_b, label_a, label_b):
    """Plain-text per-position stat summary fed to Gemini. Missing averages are
    marked NA so the model is told not to infer them."""
    lines = []
    for pos_num, pos_name in POSITION_NAMES.items():
        def _fmt(stats):
            if stats['count'] == 0:
                return "no players"
            parts = []
            for m in METRICS:
                v = stats['metrics'][m]
                parts.append(f"{METRIC_SHORT[m]}={v:.1f}" if v is not None
                             else f"{METRIC_SHORT[m]}=NA")
            return f"{stats['count']} player(s), avg " + ", ".join(parts)
        lines.append(f"{pos_name} — {label_a}: {_fmt(stats_a[pos_num])} | "
                     f"{label_b}: {_fmt(stats_b[pos_num])}")
    return "\n".join(lines)


@st.cache_data(show_spinner=False)
def generate_tvt_commentary(label_a, label_b, roster_key_a, roster_key_b,
                            summary_text, language):
    """Gemini tactical analysis of Team A vs Team B.

    Cached on every argument; roster_key_a/roster_key_b (sorted player-name
    tuples) plus summary_text fully capture each team's composition, so a unique
    matchup+language triggers at most one API call. Fed ONLY the aggregated
    numbers in summary_text. Raises on failure so the caller can warn and so
    transient errors are not cached."""
    key = _get_gemini_key()
    if not key:
        raise RuntimeError("Gemini key not configured")

    lang_line = ("Write the analysis in Turkish." if language == "Türkçe"
                 else "Write the analysis in English.")
    prompt = (
        "You are a volleyball tactical analyst comparing two teams position by "
        "position. Base your analysis ONLY on the per-position average statistics "
        "provided below (height, spike reach, block reach, jump power in cm). "
        "Stats marked NA are unavailable — never infer, estimate, or comment on "
        "them. Invent NO facts about real matches, history, results, players' "
        "careers, or anything not in these numbers.\n\n"
        "Write a concise tactical analysis (4-7 sentences) covering: where "
        f"{label_a} should attack, where {label_b} is vulnerable, the key "
        "positional matchups, and any position where a team is missing players. "
        "State clearly which team holds the overall edge.\n\n"
        f"TEAM A = {label_a}\nTEAM B = {label_b}\n\n"
        "PER-POSITION AVERAGES:\n" + summary_text + "\n\n" + lang_line
    )

    from google import genai
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    text = (resp.text or "").strip()
    if not text:
        raise ValueError("Gemini returned an empty response")
    return text


def tvt_team_input(prefix, default_country):
    """Render one team's input block (mode toggle + inputs) and return
    (team_df | None, label, roster_key | None, error | None). Used twice (Team A,
    Team B) with a unique widget-key prefix so the two blocks never clash."""
    mode = st.radio(
        "Input mode", ["Build from database", "Upload CSV"],
        key=f'{prefix}_mode', horizontal=True,
    )
    if mode == "Upload CSV":
        up = st.file_uploader("Team roster CSV", type='csv', key=f'{prefix}_upload')
        if up is None:
            return None, None, None, "Upload a CSV roster above."
        team_df, err = parse_uploaded_csv(up)
        if err:
            return None, None, None, err
        label = up.name.rsplit('.', 1)[0]
        roster_key = tuple(sorted(team_df['name'].astype(str)))
        return team_df, label, roster_key, None

    # Build-from-database mode — country-filtered, 5-1 position-slot lineup.
    countries = sorted(df_clean['country'].dropna().unique())
    idx = countries.index(default_country) if default_country in countries else 0
    country = st.selectbox("Country", countries, index=idx, key=f'{prefix}_country')
    pool = df_clean[df_clean['country'] == country]

    st.caption(
        f"Full 5-1 lineup = {TVT_LINEUP_SIZE} players "
        "(Setter ×1, Opposite ×1, Middle Blocker ×2, Outside Hitter ×2, Libero ×1). "
        "Each slot's dropdown lists only this country's players for that position; "
        "a player picked in one slot is removed from the others. Slots may be left "
        "empty for a partial lineup."
    )

    # Country-filtered name pool per position (sorted for stable dropdowns).
    names_by_pos = {
        pos_num: list(pool[pool['position_number'] == pos_num]
                      .sort_values('name')['name'])
        for pos_num, _ in TVT_LINEUP
    }
    # Every slot's widget key, in render order.
    slot_keys = [
        (pos_num, j, f'{prefix}_slot_{pos_num}_{j}')
        for pos_num, n in TVT_LINEUP
        for j in range(n)
    ]
    # Clean stale picks (e.g. after switching country) so no widget ever holds a
    # value absent from its current options — that would raise in Streamlit.
    for pos_num, _j, k in slot_keys:
        val = st.session_state.get(k)
        if val is not None and val not in names_by_pos[pos_num]:
            st.session_state[k] = None

    picked = []
    for pos_num, n in TVT_LINEUP:
        pos_name = POSITION_NAMES[pos_num]
        pos_players = names_by_pos[pos_num]
        for j in range(n):
            this_key = f'{prefix}_slot_{pos_num}_{j}'
            # Players already chosen in any OTHER slot are unavailable here. A
            # slot can never collide with its own value because every other slot
            # already excluded this slot's pick, so duplicates are impossible.
            taken = {st.session_state.get(k) for (_p, _q, k) in slot_keys
                     if k != this_key}
            taken.discard(None)
            options = [None] + [p for p in pos_players if p not in taken]
            slot_label = pos_name + (f" #{j + 1}" if n > 1 else "")
            sel = st.selectbox(
                slot_label, options, key=this_key,
                format_func=lambda v: "— (empty) —" if v is None
                else _player_labels.get(v, v),
            )
            if sel:
                picked.append(sel)

    st.caption(f"Lineup: {len(picked)}/{TVT_LINEUP_SIZE} slots filled.")
    if not picked:
        return None, country, None, f"Fill at least one {country} lineup slot."
    team_df = _team_from_db(picked)
    roster_key = tuple(sorted(picked))
    return team_df, country, roster_key, None


# ── Section 6: Data loading (cached) ───────────────────────────────────────
@st.cache_data
def load_data():
    # Wikipedia-sourced dataset (Turkey/Italy/Poland, 39 players). country is now
    # a text name; spike/block/height are blank (NaN) for players Wikipedia omits.
    # All percentiles/benchmarks below use pandas' default skipna so a blank is
    # excluded per-metric rather than dropping the whole player. clean_data.csv is
    # kept as a backup but no longer read.
    df = pd.read_csv('data/final_dataset.csv')
    df_clean = df.drop_duplicates(subset=['name']).copy()
    df_clean['jump_power']       = df_clean['spike'] - df_clean['height']
    df_clean['spike_percentile'] = df_clean['spike'].rank(pct=True) * 100
    df_clean['block_percentile'] = df_clean['block'].rank(pct=True) * 100
    df_clean['scout_score']      = (df_clean['spike_percentile'] + df_clean['block_percentile']) / 2
    df_clean['position_name']    = df_clean['position_number'].map(POSITION_NAMES)

    # date_of_birth is a DD/MM/YYYY string. Parse it to a real datetime once here;
    # errors='coerce' turns any malformed/missing value into NaT so the load never
    # crashes. Age itself is computed at render time via _compute_age() so it never
    # goes stale across a year boundary while this cached frame is held.
    if 'date_of_birth' in df_clean.columns:
        df_clean['dob'] = pd.to_datetime(
            df_clean['date_of_birth'], format='%d/%m/%Y', errors='coerce'
        )
    else:
        df_clean['dob'] = pd.NaT

    _metric_min = {m: df_clean[m].min() for m in RADAR_METRICS}
    _metric_max = {m: df_clean[m].max() for m in RADAR_METRICS}

    # Benchmark table
    benchmark_rows = []
    for pos_num, pos_name in POSITION_NAMES.items():
        pos_df = df_clean[df_clean['position_number'] == pos_num]
        if pos_df.empty:
            continue
        row = {'Position': pos_name, '_order': pos_num}
        for m in METRICS:
            row[f'{m}_avg']   = round(pos_df[m].mean(), 1)
            row[f'{m}_top25'] = round(pos_df[m].quantile(0.75), 1)
            row[f'{m}_elite'] = round(pos_df[m].quantile(0.90), 1)
        benchmark_rows.append(row)

    benchmark_df = (pd.DataFrame(benchmark_rows)
                      .sort_values('_order')
                      .drop(columns='_order')
                      .reset_index(drop=True))

    benchmark_avgs = {
        pos_num: {m: df_clean[df_clean['position_number'] == pos_num][m].mean() for m in METRICS}
        for pos_num in POSITION_NAMES
        if not df_clean[df_clean['position_number'] == pos_num].empty
    }

    _sorted = df_clean.sort_values(['position_number', 'name'])
    player_options = [
        {
            'label': f"{row['name']} — {POSITION_NAMES.get(row['position_number'], '?')}",
            'value': row['name'],
        }
        for _, row in _sorted.iterrows()
    ]

    return df_clean, _metric_min, _metric_max, benchmark_df, benchmark_avgs, player_options


# ── Section 7: Module-level data assignment (runs before any UI code path) ──
(df_clean, _metric_min, _metric_max,
 benchmark_df, benchmark_avgs, player_options) = load_data()

default_p1 = player_options[0]['value']
default_p2 = player_options[1]['value']
_player_values = [opt['value'] for opt in player_options]
_player_labels = {opt['value']: opt['label'] for opt in player_options}


# ── Section 8: UI ──────────────────────────────────────────────────────────
st.markdown(
    "<h1 style='text-align:center;color:#2c3e50;font-family:Arial;'>"
    "Voleybol Scouting Karar Destek Paneli</h1>",
    unsafe_allow_html=True,
)

tab_scout, tab_bench, tab_compare, tab_team, tab_profile, tab_tvt = st.tabs(
    ['Player Scout', 'Position Benchmarks', 'Player Comparison',
     'Team Analysis', 'Player Profile', 'Team vs Team']
)

# ── Tab 1: Player Scout ────────────────────────────────────────────────────
with tab_scout:
    c1, c2 = st.columns(2)
    with c1:
        min_spike = st.slider("Minimum Smaç Yüksekliği (cm):", 250, 350, 300, 5)
    with c2:
        max_height = st.slider("Maksimum Boy (cm):", 160, 210, 185, 1)
    st.plotly_chart(build_scout_figure(min_spike, max_height), width='stretch')

# ── Tab 2: Position Benchmarks ─────────────────────────────────────────────
with tab_bench:
    st.subheader("Position Benchmark Standards")
    st.caption("Deduplicated player records only. "
               "Top 25% = 75th percentile · Elite 10% = 90th percentile.")

    rename_map = {'Position': 'Position'}
    for m in METRICS:
        lbl = METRIC_SHORT[m]
        rename_map[f'{m}_avg']   = f'{lbl} Avg'
        rename_map[f'{m}_top25'] = f'{lbl} Top 25%'
        rename_map[f'{m}_elite'] = f'{lbl} Elite 10%'
    bench_disp  = benchmark_df.rename(columns=rename_map)
    elite_cols  = [f'{METRIC_SHORT[m]} Elite 10%' for m in METRICS]
    numeric_cols = [c for c in bench_disp.columns if c != 'Position']
    # Compute column indices so the CSS selector targets exactly the right <td> elements.
    # tr td.colN has specificity (0,1,2) — same as tr:nth-child(odd) td — but placed LAST
    # in the list, so cascade ordering makes it win.  !important adds a second layer of
    # certainty against any Streamlit dark-theme rules that also use !important.
    _elite_indices = [list(bench_disp.columns).index(c) for c in elite_cols]
    _elite_sel     = ', '.join(f'tr td.col{i}' for i in _elite_indices)
    _bench_table_styles = [
        {'selector': 'table', 'props': [('width', '100%'), ('border-collapse', 'collapse')]},
        {'selector': 'th', 'props': [
            ('background-color', '#2c3e50'), ('color', 'white'),
            ('padding', '8px 12px'), ('text-align', 'center'),
            ('font-family', 'Arial'), ('font-size', '12px'), ('font-weight', 'bold'),
        ]},
        {'selector': 'td', 'props': [
            ('color', '#e0e0e0'), ('padding', '8px 12px'), ('text-align', 'center'),
            ('font-family', 'Arial'), ('font-size', '13px'),
            ('border-bottom', '1px solid #3a3a3a'),
        ]},
        {'selector': 'tr:nth-child(odd) td', 'props': [
            ('background-color', 'rgba(255,255,255,0.04)'),
        ]},
        # Elite cells — LAST in this list so cascade order favours this rule over the
        # odd-row rule above (same specificity, later wins).
        {'selector': _elite_sel, 'props': [
            ('background-color', '#fff3cd !important'),
            ('color', '#1a1a1a !important'),
            ('font-weight', 'bold'),
        ]},
    ]
    bench_styler = (bench_disp.style
        .format("{:.1f}", subset=numeric_cols, na_rep="—")
        .hide(axis='index')
        .set_table_styles(_bench_table_styles)
    )
    st.markdown(
        f'<div style="overflow-x:auto">{bench_styler.to_html()}</div>',
        unsafe_allow_html=True,
    )

    st.markdown("**Select metric to visualise:**")
    metric = st.selectbox(
        "metric", METRICS, index=METRICS.index('spike'),
        format_func=lambda m: METRIC_LABELS[m], label_visibility='collapsed',
    )
    st.plotly_chart(build_benchmark_figure(metric), width='stretch')

# ── Tab 3: Player Comparison ───────────────────────────────────────────────
with tab_compare:
    st.subheader("Head-to-Head Player Comparison")
    st.caption("All six metrics are normalized to a 0–100 scale for visual comparison. "
               "Spike Percentile and Block Percentile show rank within the full dataset.")

    pc1, pc2 = st.columns(2)
    with pc1:
        player1 = st.selectbox(
            "Player 1", _player_values, index=0,
            format_func=lambda v: _player_labels[v],
        )
    with pc2:
        player2 = st.selectbox(
            "Player 2", _player_values, index=1,
            format_func=lambda v: _player_labels[v],
        )

    if st.button("Generate PDF Report"):
        pdf_bytes = generate_scouting_pdf(player1, player2)
        st.session_state['pdf_bytes'] = pdf_bytes
        st.session_state['pdf_name']  = (
            f"scouting_{player1.replace(' ', '_')}_vs_{player2.replace(' ', '_')}.pdf"
        )
    if st.session_state.get('pdf_bytes'):
        st.download_button(
            "Download PDF Report",
            data=st.session_state['pdf_bytes'],
            file_name=st.session_state['pdf_name'],
            mime='application/pdf',
        )
    st.caption("Generates a confidential scouting report for the two selected players.")

    radar_fig, comp_table, radar_note = build_comparison(player1, player2)
    st.plotly_chart(radar_fig, width='stretch')
    if radar_note:
        st.caption(radar_note)
    st.dataframe(comp_table, hide_index=True, width='stretch')

    # ── AI Scouting Note (Gemini) ──────────────────────────────────────────
    st.markdown("---")
    st.subheader("AI Scouting Note")
    ai_lang = st.radio(
        "Yorum dili / Commentary language",
        ["Türkçe", "English"], index=0, horizontal=True,
    )
    if _get_gemini_key() is None:
        st.info("AI commentary unavailable: Gemini key not configured")
    else:
        try:
            with st.spinner("Generating AI commentary..."):
                ai_note = generate_ai_commentary(player1, player2, ai_lang)
            st.markdown(ai_note)
        except Exception as exc:
            st.warning(f"AI commentary unavailable: {type(exc).__name__}: {exc}")

# ── Tab 4: Team Analysis ───────────────────────────────────────────────────
with tab_team:
    st.subheader("Team Analysis")
    st.caption("Upload a CSV with your team's roster to analyse squad composition, "
               "detect individual weaknesses, and get transfer recommendations.")

    st.download_button(
        "Download Sample CSV", data=SAMPLE_CSV,
        file_name='team_sample.csv', mime='text/csv',
    )
    st.caption("Required columns: name · position_number · height · spike · block")

    uploaded = st.file_uploader("Upload team roster CSV", type='csv')

    if uploaded is None:
        st.info("Upload a CSV file above to see the analysis.")
    else:
        team_df, error = parse_uploaded_csv(uploaded)
        if error:
            st.error(f"Error: {error}")
        else:
            st.success(f'Loaded "{uploaded.name}" — {len(team_df)} players')

            # Section A — Squad Overview
            st.markdown("### Section A — Squad Overview")
            st.plotly_chart(build_squad_chart(team_df), width='stretch')

            # Section B — Weakness Detection
            st.markdown("### Section B — Weakness Detection")
            st.caption("Red cells are below the position benchmark average.")
            weakness_rows, below_cells, score_rows = compute_weakness(team_df)

            st.markdown("#### Team Score by Position")
            st.caption("Score = team average as % of benchmark average. "
                       "Green ≥ 97 · Yellow ≥ 90 · Red < 90")
            score_cols = st.columns(len(score_rows))
            for col, r in zip(score_cols, score_rows):
                score_txt = f"{r['score']}%" if r['score'] is not None else '—'
                col.markdown(
                    f"<div style='text-align:center;padding:12px 8px;"
                    f"border:2px solid {r['color']};border-radius:8px;"
                    f"background-color:white;'>"
                    f"<div style='font-weight:bold;font-size:12px;color:#2c3e50;'>{r['position']}</div>"
                    f"<div style='font-size:22px;font-weight:bold;color:{r['color']};'>{score_txt}</div>"
                    f"<div style='color:{r['color']};font-size:12px;'>{r['status']}</div>"
                    f"<div style='color:#555555;font-size:11px;'>{r['players']} player(s)</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            st.write("")
            col_disp = {'name': 'Name', 'position': 'Position', 'height': 'Height (cm)',
                        'spike': 'Spike (cm)', 'block': 'Block (cm)', 'jump_power': 'Jump Power'}
            wdf = pd.DataFrame(weakness_rows).rename(columns=col_disp)
            below_disp = [(r, col_disp[c]) for r, c in below_cells]

            # Build per-cell CSS selectors (td.rowR.colC) for below-benchmark cells.
            # Placed LAST in set_table_styles with !important — same fix as benchmark table.
            _weak_numeric_cols = ['Height (cm)', 'Spike (cm)', 'Block (cm)', 'Jump Power']
            _weak_col_map = {v: i for i, v in enumerate(wdf.columns)}
            _red_selectors = [
                f'td.row{r}.col{_weak_col_map[c]}'
                for r, c in below_disp
                if c in _weak_col_map
            ]
            _weak_table_styles = [
                {'selector': 'table', 'props': [('width', '100%'), ('border-collapse', 'collapse')]},
                {'selector': 'th', 'props': [
                    ('background-color', '#2c3e50'), ('color', 'white'),
                    ('padding', '8px 12px'), ('text-align', 'center'),
                    ('font-family', 'Arial'), ('font-size', '12px'), ('font-weight', 'bold'),
                ]},
                {'selector': 'td', 'props': [
                    ('color', '#e0e0e0'), ('padding', '8px 12px'), ('text-align', 'center'),
                    ('font-family', 'Arial'), ('font-size', '13px'),
                    ('border-bottom', '1px solid #3a3a3a'),
                ]},
            ]
            if _red_selectors:
                _weak_table_styles.append({
                    'selector': ', '.join(_red_selectors),
                    'props': [
                        ('background-color', '#fde8e8 !important'),
                        ('color', '#c0392b !important'),
                        ('font-weight', 'bold'),
                    ],
                })
            weak_styler = (wdf.style
                .format("{:.1f}", subset=_weak_numeric_cols)
                .hide(axis='index')
                .set_table_styles(_weak_table_styles)
            )
            st.markdown(
                f'<div style="overflow-x:auto">{weak_styler.to_html()}</div>',
                unsafe_allow_html=True,
            )

            # Section C — Transfer Recommendations
            st.markdown("### Section C — Transfer Recommendations")
            st.caption("Top 5 candidates from the database for each weak or missing position, "
                       "ranked by combined spike + block percentile.")
            transfer_sections = build_transfer_targets(score_rows)
            if not transfer_sections:
                st.success("No weak or missing positions — great squad!")
            else:
                for r, subtitle, rec_rows in transfer_sections:
                    st.markdown(
                        f"<h5 style='color:{r['color']};font-family:Arial;'>"
                        f"{r['position']}  {subtitle}</h5>",
                        unsafe_allow_html=True,
                    )
                    st.dataframe(pd.DataFrame(rec_rows),
                                 hide_index=True, width='stretch')

# ── Tab 5: Player Profile ──────────────────────────────────────────────────
with tab_profile:
    st.subheader("Player Profile Card")
    st.caption("Pick a player to view their scouting card — initials avatar, "
               "key stats, and a detailed AI scouting profile.")

    profile_player = st.selectbox(
        "Select player", _player_values, index=0,
        format_func=lambda v: _player_labels[v], key='profile_player',
    )

    prow     = df_clean[df_clean['name'] == profile_player].iloc[0]
    pos_num  = int(prow['position_number'])
    pos_name = POSITION_NAMES.get(pos_num, 'Unknown')
    p_age    = _compute_age(prow.get('dob'))
    age_disp = str(p_age) if p_age is not None else "—"
    # country is now a text name (Turkey/Italy/Poland) — display it directly.
    country  = prow['country'] if pd.notna(prow.get('country')) else '—'

    def _metric_disp(col):
        v = _num_or_none(prow[col])
        return f"{v:.0f}" if v is not None else "—"

    # ── Card header: avatar beside identity ────────────────────────────────
    av_col, id_col = st.columns([1, 4])
    with av_col:
        st.markdown(_avatar_html(profile_player, pos_num), unsafe_allow_html=True)
    with id_col:
        st.markdown(
            f"<div style='font-size:26px;font-weight:bold;color:#e0e0e0;"
            f"font-family:Arial;'>{profile_player}</div>"
            f"<div style='display:inline-block;margin-top:6px;padding:3px 12px;"
            f"border-radius:12px;background-color:{POSITION_COLORS.get(pos_num, '#555555')};"
            f"color:#ffffff;font-size:13px;font-weight:bold;font-family:Arial;'>"
            f"{pos_name}</div>"
            f"<div style='margin-top:8px;color:#9aa5b1;font-size:13px;"
            f"font-family:Arial;'>Country: {country}　·　Age: {age_disp}</div>",
            unsafe_allow_html=True,
        )

    st.write("")

    # ── Key stats (missing values render as '—') ───────────────────────────
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Height (cm)",      _metric_disp('height'))
    s2.metric("Spike Reach (cm)", _metric_disp('spike'))
    s3.metric("Block Reach (cm)", _metric_disp('block'))
    s4.metric("Jump Power (cm)",  _metric_disp('jump_power'))
    s5, s6 = st.columns(2)
    s5.metric("Spike Percentile", _metric_disp('spike_percentile'))
    s6.metric("Block Percentile", _metric_disp('block_percentile'))

    # ── Detailed AI Scouting Profile (Gemini) ──────────────────────────────
    st.markdown("---")
    st.subheader("AI Scouting Profile")
    profile_lang = st.radio(
        "Profil dili / Profile language",
        ["Türkçe", "English"], index=0, horizontal=True, key='profile_lang',
    )
    if _get_gemini_key() is None:
        st.info("AI profile unavailable: Gemini key not configured")
    else:
        try:
            with st.spinner("Generating detailed AI profile..."):
                profile_text = generate_player_profile(profile_player, profile_lang)
            st.markdown(profile_text)
        except Exception as exc:
            st.warning(f"AI profile unavailable: {type(exc).__name__}: {exc}")

# ── Tab 6: Team vs Team ────────────────────────────────────────────────────
with tab_tvt:
    st.subheader("Team vs Team Comparison")
    st.caption("Compare two teams position-by-position. Each team can be built "
               "from the database (country-filtered) or uploaded as a CSV roster. "
               "Players with blank spike/block are excluded per-metric from averages.")

    # Sample roster downloads (for testing the CSV-upload mode).
    st.markdown("**Sample rosters** (download, then upload via 'Upload CSV' mode):")
    dl1, dl2, dl3 = st.columns(3)
    dl1.download_button("Turkey sample", data=SAMPLE_TEAM_TR,
                        file_name='sample_team_turkey.csv', mime='text/csv',
                        key='tvt_dl_tr')
    dl2.download_button("Italy sample", data=SAMPLE_TEAM_IT,
                        file_name='sample_team_italy.csv', mime='text/csv',
                        key='tvt_dl_it')
    dl3.download_button("Poland sample", data=SAMPLE_TEAM_PL,
                        file_name='sample_team_poland.csv', mime='text/csv',
                        key='tvt_dl_pl')

    st.markdown("---")

    # ── Team inputs (independent modes) ────────────────────────────────────
    in_a, in_b = st.columns(2)
    with in_a:
        st.markdown("### Team A")
        team_a_df, label_a_src, key_a, err_a = tvt_team_input('tvt_a', 'Turkey')
    with in_b:
        st.markdown("### Team B")
        team_b_df, label_b_src, key_b, err_b = tvt_team_input('tvt_b', 'Italy')

    # Distinct column labels (the A/B prefix guarantees uniqueness even if both
    # teams pick the same country).
    label_a = f"A · {label_a_src}" if label_a_src else "Team A"
    label_b = f"B · {label_b_src}" if label_b_src else "Team B"

    if team_a_df is None or team_b_df is None:
        if err_a:
            st.info(f"Team A: {err_a}")
        if err_b:
            st.info(f"Team B: {err_b}")
        st.caption("Configure both teams above to see the comparison.")
    else:
        st.success(f"Comparing {label_a} ({len(team_a_df)} players) vs "
                   f"{label_b} ({len(team_b_df)} players)")

        # Roster previews
        rp_a, rp_b = st.columns(2)
        _roster_cols = {'name': 'Name', 'position_name': 'Position',
                        'height': 'Height', 'spike': 'Spike',
                        'block': 'Block', 'jump_power': 'Jump Pwr'}
        with rp_a:
            st.markdown(f"**{label_a} roster**")
            st.dataframe(team_a_df[list(_roster_cols)].rename(columns=_roster_cols),
                         hide_index=True, width='stretch')
        with rp_b:
            st.markdown(f"**{label_b} roster**")
            st.dataframe(team_b_df[list(_roster_cols)].rename(columns=_roster_cols),
                         hide_index=True, width='stretch')

        stats_a = _team_position_stats(team_a_df)
        stats_b = _team_position_stats(team_b_df)

        # ── Position-by-position chart ─────────────────────────────────────
        st.markdown("### Position-by-Position Averages")
        tvt_metric = st.selectbox(
            "Metric to chart", METRICS, index=METRICS.index('spike'),
            format_func=lambda m: METRIC_LABELS[m], key='tvt_metric',
        )
        st.plotly_chart(
            build_tvt_position_chart(stats_a, stats_b, label_a, label_b, tvt_metric),
            width='stretch',
        )

        # ── Detailed comparison table ──────────────────────────────────────
        st.markdown("#### Detailed comparison")
        st.caption("Green cell = the stronger team for that position & metric. "
                   "'—' means one team has no player / no value there.")
        st.markdown(
            f'<div style="overflow-x:auto">'
            f'{_tvt_table_html(stats_a, stats_b, label_a, label_b)}</div>',
            unsafe_allow_html=True,
        )

        # ── Strengths / weaknesses + tactical warnings ─────────────────────
        a_adv, b_adv, even, warnings = tvt_summary_and_warnings(
            stats_a, stats_b, label_a, label_b)

        st.markdown("### Strengths & Weaknesses")
        sw_a, sw_b, sw_e = st.columns(3)
        with sw_a:
            st.markdown(f"**{label_a} advantage**")
            st.markdown("\n".join(f"- {p}" for p in a_adv) if a_adv
                        else "_None_")
        with sw_b:
            st.markdown(f"**{label_b} advantage**")
            st.markdown("\n".join(f"- {p}" for p in b_adv) if b_adv
                        else "_None_")
        with sw_e:
            st.markdown("**Even**")
            st.markdown("\n".join(f"- {p}" for p in even) if even
                        else "_None_")

        st.markdown("### Tactical Warnings")
        if warnings:
            for w in warnings:
                st.warning(w)
        else:
            st.success("No missing positions or one-sided mismatches detected.")

        # ── Gemini tactical commentary ─────────────────────────────────────
        st.markdown("---")
        st.subheader("AI Tactical Analysis")
        tvt_lang = st.radio(
            "Analiz dili / Analysis language",
            ["Türkçe", "English"], index=0, horizontal=True, key='tvt_lang',
        )
        if _get_gemini_key() is None:
            st.info("AI analysis unavailable: Gemini key not configured")
        else:
            summary_text = _tvt_gemini_summary(stats_a, stats_b, label_a, label_b)
            try:
                with st.spinner("Generating AI tactical analysis..."):
                    tvt_note = generate_tvt_commentary(
                        label_a, label_b, key_a, key_b, summary_text, tvt_lang)
                st.markdown(tvt_note)
            except Exception as exc:
                st.warning(f"AI analysis unavailable: {type(exc).__name__}: {exc}")
