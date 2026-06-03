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

def normalize(value, metric):
    mn, mx = _metric_min[metric], _metric_max[metric]
    if mx == mn:
        return 50.0
    return round((value - mn) / (mx - mn) * 100, 1)


def _pct_rank(value, col):
    """Fraction of df_clean rows with col <= value, expressed as 0-100."""
    return round((df_clean[col] <= value).mean() * 100, 1)


def _player_metric_table(row):
    data = [['Metric', 'Value', 'Percentile Rank']]
    for label, col, unit in PDF_METRICS:
        val = float(row[col])
        pct = _pct_rank(val, col)
        data.append([label, f"{val:.1f} {unit}", f"{pct}%"])
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
        v1, v2 = float(row1[col]), float(row2[col])
        s1 = f"{v1:.1f} {unit}"
        s2 = f"{v2:.1f} {unit}"
        if v1 > v2:
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

    p1_leads, p2_leads = [], []
    for label, col, _ in PDF_METRICS:
        v1, v2 = float(row1[col]), float(row2[col])
        if v1 > v2:
            p1_leads.append(label)
        elif v2 > v1:
            p2_leads.append(label)

    p1_wins, p2_wins = len(p1_leads), len(p2_leads)
    total = len(PDF_METRICS)

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
        # Spike tiebreaker
        if float(row1['spike']) >= float(row2['spike']):
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

    # Jump power note (meaningful if gap ≥ 8 cm)
    jp1, jp2 = float(row1['jump_power']), float(row2['jump_power'])
    jp_note = ''
    if abs(jp1 - jp2) >= 8:
        jp_winner = p1_name if jp1 > jp2 else p2_name
        jp_note = (
            f" A jump-power differential of {abs(jp1 - jp2):.0f} cm in favour of "
            f"{jp_winner} signals superior explosive ability at the net."
        )

    # Spike percentile note (meaningful if gap ≥ 10 pp)
    sp1, sp2 = float(row1['spike_percentile']), float(row2['spike_percentile'])
    sp_note = ''
    if abs(sp1 - sp2) >= 10:
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
                'Country':    int(row['country']) if pd.notna(row['country']) else '?',
                'Height (cm)': int(row['height']),
                'Spike (cm)':  int(row['spike']),
                'Block (cm)':  int(row['block']),
                'Jump Power':  int(row['jump_power']),
                'Spike %ile':  round(row['spike_percentile'], 1),
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

    categories  = [RADAR_LABELS[m] for m in RADAR_METRICS]
    cats_closed = categories + [categories[0]]
    p1_norm = [normalize(row1[m], m) for m in RADAR_METRICS]
    p2_norm = [normalize(row2[m], m) for m in RADAR_METRICS]

    fig = go.Figure()
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

    pos1 = POSITION_NAMES.get(row1['position_number'], '?')
    pos2 = POSITION_NAMES.get(row2['position_number'], '?')
    table_rows = (
        [{'Metric': 'Position', player1: pos1, player2: pos2}] +
        [{'Metric': RADAR_RAW_LABELS[m],
          player1: str(round(row1[m], 1)), player2: str(round(row2[m], 1))}
         for m in RADAR_METRICS]
    )
    table_df = pd.DataFrame(table_rows)
    return fig, table_df


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

    def _stat_block(name, row):
        pos = POSITION_NAMES.get(int(row['position_number']), 'Unknown')
        return (
            f"{name} (position: {pos}): "
            f"height={float(row['height']):.0f} cm, "
            f"spike reach={float(row['spike']):.0f} cm, "
            f"block reach={float(row['block']):.0f} cm, "
            f"jump power={float(row['jump_power']):.0f} cm, "
            f"spike percentile={float(row['spike_percentile']):.0f}, "
            f"block percentile={float(row['block_percentile']):.0f}"
        )

    lang_line = ("Write the note in Turkish." if language == "Türkçe"
                 else "Write the note in English.")

    prompt = (
        "You are a volleyball scout writing a brief head-to-head note comparing "
        "two players. Base your comparison ONLY on the statistics provided below. "
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


# ── Section 6: Data loading (cached) ───────────────────────────────────────
@st.cache_data
def load_data():
    df = pd.read_csv('clean_data.csv')
    df_clean = df.drop_duplicates(subset=['name']).copy()
    df_clean['jump_power']       = df_clean['spike'] - df_clean['height']
    df_clean['spike_percentile'] = df_clean['spike'].rank(pct=True) * 100
    df_clean['block_percentile'] = df_clean['block'].rank(pct=True) * 100
    df_clean['scout_score']      = (df_clean['spike_percentile'] + df_clean['block_percentile']) / 2
    df_clean['position_name']    = df_clean['position_number'].map(POSITION_NAMES)

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

tab_scout, tab_bench, tab_compare, tab_team = st.tabs(
    ['Player Scout', 'Position Benchmarks', 'Player Comparison', 'Team Analysis']
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
        .format("{:.1f}", subset=numeric_cols)
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

    radar_fig, comp_table = build_comparison(player1, player2)
    st.plotly_chart(radar_fig, width='stretch')
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
