---
name: scouting-report
description: Add new analyses, filters, or metrics to the volleyball scouting notebook. Use when extending position analysis, adding new derived metrics, or modifying dashboard filter logic.
disable-model-invocation: false
---

You are helping extend the volleyball scouting analysis in `Model.ipynb`. The notebook analyzes player physical attributes (height, weight, spike height, block height) grouped by playing position.

## Key context before making changes

- Position numbers: 1=Setter, 2=Opposite, 3=Middle blocker, 4=Outside hitter, 6=Libero
- `jump_power = spike - height` (existing efficiency metric)
- `clean_data.csv` contains duplicate rows per player — always deduplicate with `df.drop_duplicates('name')` before computing per-player stats
- Country codes are numeric (23=Russia, 30/31=Brazil) — avoid filtering on country name
- Dash app runs on port 8060; do not change this unless the user asks

## When adding a new analysis

1. Check whether it belongs in cell 2 (position aggregation), cell 3 (static plot), or cell 4 (dashboard filter)
2. Use deduplicated data for per-player metrics; use the full dataset only for population-level stats
3. Match existing code style: English variable names, Turkish comments are acceptable but English is fine too
4. If adding a new slider or filter to the Dash dashboard, calculate the min/max from the actual data rather than hardcoding range values

## When adding a new metric

Define it clearly alongside `jump_power` in cell 2, and add it to the hover data in the Dash scatter plot so scouts can see it without re-running cells.
