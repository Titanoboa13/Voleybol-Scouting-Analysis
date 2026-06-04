# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Volleyball player scouting and performance analysis tool. Loads player data, performs position-based statistical analysis, and serves an interactive Streamlit dashboard for scout/coach decision-making.

`Model.ipynb` is kept as a legacy Dash reference only — it is not the runnable app.

## Setup

Install dependencies (global pip, no venv — streamlit.exe is not on PATH):

```
pip install streamlit==1.58.0 pandas plotly reportlab google-genai==2.7.0
```

`clean_data.csv` must be in the project root.

## Running the App

```
python -m streamlit run app.py --server.port 8060
```

Access at `http://127.0.0.1:8060`. Use `python -m streamlit`, not bare `streamlit` — the executable is not on PATH.

## Streamlit Architecture

- **`load_data()`** — decorated with `@st.cache_data`; reads **`data/final_dataset.csv`** (the Wikipedia-scraped dataset: 39 women's players from Turkey/Italy/Poland), deduplicates, computes `jump_power`, percentile columns, `scout_score`, benchmark stats, and player option lists. Returns everything needed by the UI. Module-level assignment in Section 7 runs before any UI code so helpers that reference globals (`normalize`, `_pct_rank`) are never called before the data exists. **`clean_data.csv` is kept only as a backup and is no longer read.** The dataset is git-ignored (local only) — see `scrape_wikipedia.py` for how it was built.
- **New-schema / missing-data handling** (added when migrating off `clean_data.csv`):
  - `country` is now a **text name** ("Turkey"/"Italy"/"Poland"), not a numeric code. Anywhere it is displayed it is used verbatim — never `int()`-cast.
  - `spike` and/or `block` are **blank (NaN)** for ~10 players Wikipedia doesn't fully cover (3 of them also lack `height`/`date_of_birth`). These players still appear everywhere (selectboxes, profile) but are **excluded per-metric** from any calculation that needs the missing value.
  - `jump_power` (= `spike − height`) is NaN when either input is missing; `spike_percentile`/`block_percentile` (via `rank(pct=True)`) and `scout_score` are NaN when their base stat is missing. Percentiles are now ranked **within these 39 players** (expected — small reference set).
  - Benchmark averages/quantiles rely on pandas' **default skipna** (`mean`/`quantile`) so one blank doesn't poison a position's benchmark; rows are never wholesale `dropna`'d.
  - The helper **`_num_or_none(value)`** (returns `float` or `None`) and **`_fmt_int(value)`** centralise the guarding. Every display path (PDF tables, radar, profile metrics, transfer recs, AI prompts) renders a missing value as **"—"**. The radar (`build_comparison`) plots only axes both players have and returns a `note` listing omitted axes; with <3 shared axes it shows a "not enough shared metrics" annotation instead of crashing. The AI prompts list `UNAVAILABLE` stats and instruct Gemini not to infer/invent them.
- **4 tabs** via `st.tabs`: Player Scout · Position Benchmarks · Player Comparison · Team Analysis.
- **Pure-logic helpers** (`normalize`, `_pct_rank`, `_player_metric_table`, `_h2h_comparison_table`, `_build_recommendation`, `generate_scouting_pdf`) are ported verbatim from `Model.ipynb` with no Streamlit dependency.
- **Benchmark and weakness tables** rendered via `st.markdown(styler.to_html(), unsafe_allow_html=True)` — required because `st.dataframe`'s Arrow grid overrides custom text colors from pandas Styler on Streamlit's dark theme. Highlighted cells use `set_table_styles` with per-cell CSS class selectors (`td.rowR.colC` / `tr td.colN`) placed last in the style list with `!important` so they win on every row regardless of theme.
- **PDF generation** is lazy: clicking "Generate PDF Report" builds bytes into `st.session_state`; the download button appears only after generation.
- **Gemini AI commentary** (Player Comparison tab): uses `google-genai==2.7.0` SDK, model `gemini-2.5-flash`. Key is read from `st.secrets["GEMINI_API_KEY"]` (stored in `.streamlit/secrets.toml`, git-ignored). The feature degrades gracefully — the tab works fully with no key present. Commentary is cached in `st.session_state` keyed by the player pair so repeat views skip the API call. A Türkçe/English toggle controls the language of the AI output. Helper: `_get_gemini_key()` returns the key or `None` without raising.
- **Player Profile tab** (tab 5): shows an initials avatar (coloured by position via `POSITION_COLORS` — a constant dict keyed by position number, reusable for future charts/badges), player name with a coloured position badge, age computed from `date_of_birth` (parsed once in `load_data()` via `pd.to_datetime(format='%d/%m/%Y', errors='coerce')` into a `dob` column; `_compute_age()` converts it to an integer at render time so the cached frame never goes stale), and six `st.metric` stat tiles. Detailed AI scouting profile via `generate_player_profile(player_name, language)` (`@st.cache_data`, same Gemini + graceful-degradation pattern, TR/EN toggle, 3-paragraph structure: Strengths / Weaknesses / Overall). Photo upload is deferred to a future phase. **The country name is now displayed** in the identity block (e.g. "Country: Turkey · Age: 26") — the old numeric-country-code problem is fixed by the new dataset, which stores real country names. Stat tiles render "—" for any missing value.

## Environment

- Python 3.14.5 · pandas 3.0.3 · plotly 6.7.0 · reportlab 4.5.1 · streamlit 1.58.0 · google-genai 2.7.0
- No breaking changes in pandas 3.0 for `rank(pct=True)`, `quantile`, or `mean` defaults.
- `streamlit.exe` not on PATH — always launch via `python -m streamlit`.

## Notebook Cell Order (legacy reference)

Cells in `Model.ipynb` must be run in sequence — each depends on variables from the previous:

1. Data loading and basic exploration
2. Position-based aggregation and `jump_power` metric
3. Deduplication and static matplotlib/seaborn visualization
4. Dash interactive dashboard

## Data Quirks

- **Two datasets**: The app now reads **`data/final_dataset.csv`** (Wikipedia-scraped, 39 players, `country` as text, some blank spike/block). The legacy **`clean_data.csv`** (numeric country codes, multiple historical rows per player, no blanks) is retained only as a backup. The notes below about duplicate rows and numeric country codes describe the **legacy `clean_data.csv`**, not the live dataset.
- **Duplicate rows (legacy `clean_data.csv` only)**: contains multiple rows per player (historical snapshots). Deduplication (`df.drop_duplicates('name')`) happens in `load_data()` (the live dataset has no duplicates, so this is a harmless no-op there).
- **Country (live dataset)**: a **text name** ("Turkey"/"Italy"/"Poland"). *(Legacy `clean_data.csv` used numeric codes with no legend — known mappings 23 = Russia, 30/31 = Brazil.)*
- **Scraper**: `scrape_wikipedia.py` (7-team full run) and `scrape_wikipedia_test.py` (Turkey+Italy test) build the dataset from Wikipedia via a two-layer scrape (national-team roster → per-player infobox). `data/final_dataset.csv` is the Turkey/Italy/Poland subset; all `data/*.csv` are git-ignored (stay local).
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
