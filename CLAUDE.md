# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Volleyball player scouting and performance analysis tool. Loads player data, performs position-based statistical analysis, and serves an interactive Dash dashboard for scout/coach decision-making.

## Setup

Install dependencies (Anaconda Python assumed):

```
pip install dash plotly pandas matplotlib seaborn
```

`clean_data.csv` must be in the project root — the notebook uses a relative path and will fail if run from another directory.

## Running the Dashboard

The Dash app runs on port **8060**. Start it by executing the final cell in `Model.ipynb`. Access at `http://127.0.0.1:8060`.

## Notebook Cell Order

Cells must be run in sequence — each cell depends on variables defined in the previous one:

1. Data loading and basic exploration
2. Position-based aggregation and `jump_power` metric
3. Deduplication and static matplotlib/seaborn visualization
4. Dash interactive dashboard

## Data Quirks

- **Duplicate rows**: `clean_data.csv` contains multiple rows per player (historical snapshots). Deduplication (`df.drop_duplicates('name')`) only happens in cell 3. Cells 1–2 operate on duplicated data — account for this in any aggregate stats.
- **Country codes are numeric**: No legend is stored in the data. Known mappings: 23 = Russia, 30/31 = Brazil.
- **Position number mapping**:
  - 1 = Setter
  - 2 = Opposite hitter
  - 3 = Middle blocker
  - 4 = Outside hitter
  - 6 = Libero
- **`jump_power` metric**: Derived as `spike − height`. Represents jumping efficiency relative to standing height.
- **Slider ranges are hardcoded**: Spike 250–350 cm, height 160–210 cm. These may not cover all data extremes.

## Code Style

Comments in the notebook are written in Turkish. Variable names and column names are in English.
