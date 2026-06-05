# Volleyball Scouting & Decision Support System

An interactive, data-driven scouting platform for professional volleyball coaches and recruitment teams. Analyse athlete performance metrics, benchmark squads against position standards, compare players head-to-head, generate confidential PDF scouting reports, and get AI-generated tactical analysis — all from a single Streamlit dashboard.

---

## Features

### 1. Player Scout
Filter the full player database by minimum spike reach and maximum height. Results update in real time as a scatter plot coloured and sized by Jump Power, making it easy to spot efficient athletes who punch above their height.

### 2. Position Benchmarks
View average, top 25% (75th percentile), and elite 10% (90th percentile) thresholds for every physical metric across all five playing positions. A grouped bar chart lets you switch between Height, Spike Reach, Block Reach, and Jump Power at a click.

### 3. Player Comparison
Select any two players from the database to see a head-to-head radar chart across up to six normalised metrics: Height, Spike Reach, Block Reach, Jump Power, Spike Percentile, and Block Percentile (axes with missing data for either player are automatically excluded). A raw-value summary table sits below the chart.

Click **Generate PDF Report** to download a formatted, confidential scouting report that includes individual metric tables with percentile ranks, a colour-coded head-to-head comparison table (winning cells highlighted green), and a written scout recommendation paragraph.

**AI Commentary** — a Gemini-powered short analysis of the matchup is generated on demand, with a Türkçe/English toggle.

### 4. Team Analysis
Upload a CSV roster (columns: `name`, `position_number`, `height`, `spike`, `block`) to get three automated sections:

- **Squad Overview** — bar chart of players per position; missing positions highlighted in red.
- **Weakness Detection** — each player compared against position benchmark averages; below-average cells highlighted; colour-coded team score cards per position (Strong / Average / Weak).
- **Transfer Recommendations** — for every weak or missing position, the top 5 candidates from the database ranked by combined spike + block percentile, with full stats displayed.

A sample CSV download button is provided so you always know the expected format.

### 5. Player Profile
Single-player card with an initials avatar coloured by position, a position badge, age computed from date of birth, and six key stat tiles. Blank stats (spike/block missing for ~10 players in the dataset) render as "—" rather than crashing.

**AI Scouting Profile** — a three-paragraph Gemini-generated write-up (Strengths / Weaknesses / Overall assessment), cached per player so repeat views skip the API call. Türkçe/English toggle.

### 6. Team vs Team
Compare two custom teams position-by-position. Each team can be configured in one of two ways:

- **Upload CSV** — same format as Team Analysis; accepts any roster shape.
- **Build from database** — country-filtered 5-1 lineup builder. Pick a country (Turkey / Italy / Poland), then fill 7 positional slots (Setter ×1, Opposite Hitter ×1, Middle Blocker ×2, Outside Hitter ×2, Libero ×1) via individual dropdowns. Each dropdown shows only that country's players for that position; a player selected in one slot is hidden from duplicate slots.

Comparison output: per-position average stats table (stronger side highlighted green), a selectable grouped bar chart, a strengths/weaknesses summary, tactical warnings for missing positions or clear mismatches, and a Gemini-generated tactical analysis paragraph. Türkçe/English toggle.

---

## How to Run

**1. Install dependencies**

```bash
pip install -r requirements.txt
```

**2. Place the dataset**

The dataset (`data/final_dataset.csv`) is kept local and is not committed to the repository. It is built by `scrape_wikipedia.py` from Wikipedia's national-team rosters (Turkey, Italy, Poland — ~39 women's players). Stats are CC-licensed factual data sourced from Wikipedia infoboxes.

**3. Configure the Gemini API key (optional)**

The app works fully without a key — AI features degrade gracefully. To enable them, create `.streamlit/secrets.toml` (this path is git-ignored and will never be committed):

```toml
GEMINI_API_KEY = "your-key-here"
```

**4. Run the app**

```bash
python -m streamlit run app.py --server.port 8060
```

> `streamlit.exe` is not on PATH — always use the `python -m streamlit` form.

**5. Open the dashboard**

Navigate to `http://127.0.0.1:8060` in your browser.

> `Model.ipynb` is retained as a legacy Dash reference only and is not the runnable app.

---

## Dataset

**Source:** Wikipedia national-team roster pages and per-player infoboxes, scraped via `scrape_wikipedia.py`. Data is factual and CC-licensed.

**Coverage:** ~39 women's players from Turkey, Italy, and Poland national teams.

**File:** `data/final_dataset.csv` (local only — git-ignored)

| Column | Description |
|--------|-------------|
| `name` | Player full name |
| `date_of_birth` | Date of birth (`DD/MM/YYYY`) |
| `height` | Standing height in cm |
| `spike` | Spike reach in cm (may be blank for some players) |
| `block` | Block reach in cm (may be blank for some players) |
| `position_number` | Numeric position code (see mapping below) |
| `country` | Country name — "Turkey", "Italy", or "Poland" |

**Missing data:** ~10 players have blank spike and/or block values (Wikipedia coverage gaps). The app handles these per-metric — affected players still appear everywhere but are excluded from any calculation that needs the missing value. Blank stats render as "—".

### Position Number Mapping

| Number | Position |
|--------|----------|
| 1 | Setter |
| 2 | Opposite Hitter |
| 3 | Middle Blocker |
| 4 | Outside Hitter |
| 6 | Libero |

### Derived Metrics

| Metric | Formula | Meaning |
|--------|---------|---------|
| `jump_power` | `spike − height` | Explosive jumping efficiency relative to standing height |
| `spike_percentile` | `rank(pct=True) × 100` | Spike reach rank within the dataset |
| `block_percentile` | `rank(pct=True) × 100` | Block reach rank within the dataset |
| `scout_score` | weighted composite | Overall scouting rank (NaN when base stats missing) |

---

## Tech Stack

| Layer | Libraries / Tools |
|-------|-------------------|
| Language | Python 3.14 |
| Dashboard framework | Streamlit 1.58 |
| Data processing | Pandas 3.0 |
| Visualisation | Plotly 6.7 |
| PDF generation | ReportLab 4.5 |
| AI commentary | Google Gemini (`gemini-2.5-flash`) via `google-genai` 2.7 |

---

## Contact

Built by a Software Engineer with a passion for volleyball analytics. Currently seeking opportunities to apply Python, data engineering, and interactive dashboard skills to help elite clubs optimise their scouting and performance analysis workflows.

**Email:** erginsen06@gmail.com
