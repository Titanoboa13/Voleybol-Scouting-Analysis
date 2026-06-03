# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Volleyball player scouting and performance analysis tool. Loads player data, performs position-based statistical analysis, and serves an interactive Streamlit dashboard for scout/coach decision-making.

`Model.ipynb` is kept as a legacy Dash reference only — it is not the runnable app.

## Setup

Install dependencies (global pip, no venv — streamlit.exe is not on PATH):

```
pip install streamlit==1.58.0 pandas plotly reportlab
```

`clean_data.csv` must be in the project root.

## Running the App

```
python -m streamlit run app.py --server.port 8060
```

Access at `http://127.0.0.1:8060`. Use `python -m streamlit`, not bare `streamlit` — the executable is not on PATH.

## Streamlit Architecture

- **`load_data()`** — decorated with `@st.cache_data`; reads `clean_data.csv`, deduplicates, computes `jump_power`, percentile columns, `scout_score`, benchmark stats, and player option lists. Returns everything needed by the UI. Module-level assignment in Section 7 runs before any UI code so helpers that reference globals (`normalize`, `_pct_rank`) are never called before the data exists.
- **4 tabs** via `st.tabs`: Player Scout · Position Benchmarks · Player Comparison · Team Analysis.
- **Pure-logic helpers** (`normalize`, `_pct_rank`, `_player_metric_table`, `_h2h_comparison_table`, `_build_recommendation`, `generate_scouting_pdf`) are ported verbatim from `Model.ipynb` with no Streamlit dependency.
- **Benchmark and weakness tables** rendered via `st.markdown(styler.to_html(), unsafe_allow_html=True)` — required because `st.dataframe`'s Arrow grid overrides custom text colors from pandas Styler on Streamlit's dark theme. Highlighted cells use `set_table_styles` with per-cell CSS class selectors (`td.rowR.colC` / `tr td.colN`) placed last in the style list with `!important` so they win on every row regardless of theme.
- **PDF generation** is lazy: clicking "Generate PDF Report" builds bytes into `st.session_state`; the download button appears only after generation.

## Environment

- Python 3.14.5 · pandas 3.0.3 · plotly 6.7.0 · reportlab 4.5.1 · streamlit 1.58.0
- No breaking changes in pandas 3.0 for `rank(pct=True)`, `quantile`, or `mean` defaults.
- `streamlit.exe` not on PATH — always launch via `python -m streamlit`.

## Notebook Cell Order (legacy reference)

Cells in `Model.ipynb` must be run in sequence — each depends on variables from the previous:

1. Data loading and basic exploration
2. Position-based aggregation and `jump_power` metric
3. Deduplication and static matplotlib/seaborn visualization
4. Dash interactive dashboard

## Data Quirks

- **Duplicate rows**: `clean_data.csv` contains multiple rows per player (historical snapshots). Deduplication (`df.drop_duplicates('name')`) only happens in cell 3 of the notebook / `load_data()` in the app. Cells 1–2 of the notebook operate on duplicated data.
- **Country codes are numeric**: No legend is stored in the data. Known mappings: 23 = Russia, 30/31 = Brazil.
- **Position number mapping**:
  - 1 = Setter
  - 2 = Opposite hitter
  - 3 = Middle blocker
  - 4 = Outside hitter
  - 6 = Libero
- **`jump_power` metric**: Derived as `spike − height`. Represents jumping efficiency relative to standing height.
- **Slider ranges are hardcoded**: Spike 250–350 cm, height 160–210 cm. These may not cover all data extremes.

## Secrets

Store the Gemini API key (and any future keys) in `.streamlit/secrets.toml` — that path is in `.gitignore` and will never be committed. Do not hardcode keys in any `.py` or `.ipynb` file.

## Code Style

Comments in the notebook are written in Turkish. Variable names and column names are in English.
