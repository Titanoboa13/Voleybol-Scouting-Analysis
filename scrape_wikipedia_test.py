"""
Wikipedia volleyball roster scraper -- EXPLORATORY TEST (Turkey + Italy women).

Goal: rebuild a fresh, accurate player dataset from Wikipedia (CC-licensed,
factual stats are not copyrightable). This is a TEST run on two national teams
to gauge data quality before scaling up.

Two-layer scrape:
  Layer 1 -- national team page "Current squad": player names + position + (sometimes) stats.
  Layer 2 -- each player's personal page infobox: height, spike, block, weight, DOB, club.

Politeness: clear User-Agent, ~1.5s delay between requests, no hammering.

Output: data/new_dataset_test.csv  (does NOT touch clean_data.csv or app.py).
Dates are written as DD/MM/YYYY to match the existing app schema.
"""

import re
import sys
import time
import requests
import pandas as pd

# --- UTF-8 console so Turkish/Italian names print correctly on Windows -------
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

API = "https://en.wikipedia.org/w/api.php"
HEADERS = {
    "User-Agent": "VolleyballScoutingBot/1.0 (educational project)"
}
DELAY = 1.5  # seconds between page requests -- be polite to Wikipedia

TEAMS = {
    "Turkey": "Turkey women's national volleyball team",
    "Italy": "Italy women's national volleyball team",
}

# Position abbreviation -> existing app's numeric scheme
# 1=Setter 2=Opposite 3=Middle Blocker 4=Outside Hitter 6=Libero
POS_ABBR = {
    "S": 1,
    "OP": 2, "OS": 2,            # Opposite / Opposite Spiker
    "MB": 3,
    "OH": 4, "WS": 4,            # Outside Hitter / Wing Spiker
    "L": 6,
}
# Fallback: free-text position from an infobox
POS_TEXT = [
    ("libero", 6),
    ("setter", 1),
    ("middle", 3),               # middle blocker
    ("outside", 4),
    ("wing spiker", 4),
    ("opposite", 2),
]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def get_wikitext(page):
    """Return raw wikitext for a page (following redirects), or None if missing."""
    params = {
        "action": "parse", "page": page, "prop": "wikitext",
        "format": "json", "redirects": 1,
    }
    try:
        r = requests.get(API, params=params, headers=HEADERS, timeout=30)
        data = r.json()
    except Exception as e:
        print(f"   ! request failed for {page!r}: {e}", file=sys.stderr)
        return None
    if "parse" not in data:
        return None
    return data["parse"]["wikitext"]["*"]


# ---------------------------------------------------------------------------
# Wikitext helpers
# ---------------------------------------------------------------------------
def extract_current_squad(wt):
    """Slice out the 'Current squad' section (up to the next heading)."""
    m = re.search(r"==+\s*Current squad\s*==+(.*?)(?=\n==[^=])", wt, re.S | re.I)
    if not m:
        # some pages just say "Squad" / "Team roster"
        m = re.search(r"==+\s*(?:Squad|Team roster|Roster)\s*==+(.*?)(?=\n==[^=])",
                      wt, re.S | re.I)
    return m.group(1) if m else ""


def split_link(link):
    """[[Target|Display]] content -> (page_title, display_name)."""
    if "|" in link:
        target, disp = link.split("|", 1)
        return target.strip(), disp.strip()
    return link.strip(), link.strip()


def parse_roster(section):
    """
    Return list of dicts: {page, name, pos_abbr, r_height, r_block, r_spike, r_dob}
    Handles both the wikitable format (Turkey) and the bulleted-list format (Italy).
    Roster-derived stats (r_*) are used only as a fallback for missing infobox data.
    """
    players = []
    is_table = "{|" in section and "{{abbr" in section.lower()

    if is_table:
        # locate header to map stat columns by name (order varies between pages)
        header = next((ln for ln in section.splitlines()
                       if "height" in ln.lower() and "spike" in ln.lower()), "")
        hcells = [c.lower() for c in header.split("!!")]

        def col(keyword):
            for i, c in enumerate(hcells):
                if keyword in c:
                    return i
            return None

        ih, ib, isp = col("height"), col("block"), col("spike")
        idob = next((i for i, c in enumerate(hcells) if "birth" in c), None)

        for row in re.split(r"\n\|-", section):
            am = re.search(r"\{\{abbr\|([^|}]+)\|", row)        # first abbr = position
            lm = re.search(r"\[\[([^\]]+)\]\]", row)            # first link = player
            if not (am and lm):
                continue
            pos = am.group(1).strip().upper()
            if pos not in POS_ABBR:        # skip rows whose first abbr isn't a position
                continue
            page, name = split_link(lm.group(1))
            cells = [c.strip() for c in row.split("||")]
            cells[0] = cells[0].lstrip("|").strip() if cells else ""

            def cell(i):
                return cells[i] if i is not None and i < len(cells) else ""

            players.append({
                "page": page, "name": name, "pos_abbr": pos,
                "r_height": parse_length(cell(ih)),
                "r_block": parse_length(cell(ib)),
                "r_spike": parse_length(cell(isp)),
                "r_dob": parse_dob(cell(idob)),
            })
    else:
        # bulleted list: "* 3 [[Name]] (S)"
        for line in section.splitlines():
            line = line.strip()
            if not line.startswith("*"):
                continue
            lm = re.search(r"\[\[([^\]]+)\]\]", line)
            pm = re.search(r"\(([A-Za-z/]{1,3})\)\s*$", line)
            if not (lm and pm):
                continue
            pos = pm.group(1).strip().upper()
            page, name = split_link(lm.group(1))
            players.append({
                "page": page, "name": name, "pos_abbr": pos,
                "r_height": None, "r_block": None, "r_spike": None, "r_dob": None,
            })
    return players


def extract_infobox(wt):
    """Return the volleyball-player/biography infobox wikitext via brace matching."""
    low = wt.lower()
    i = low.find("{{infobox volleyball")
    if i < 0:
        return None
    depth, j = 0, i
    while j < len(wt) - 1:
        two = wt[j:j + 2]
        if two == "{{":
            depth += 1
            j += 2
        elif two == "}}":
            depth -= 1
            j += 2
            if depth == 0:
                return wt[i:j]
        else:
            j += 1
    return wt[i:]


def infobox_params(infobox):
    """Parse top-level | key = value pairs (respecting nested {{}} and [[]])."""
    s = infobox[2:-2]  # strip outer {{ }}
    parts, buf, depth = [], "", 0
    k = 0
    while k < len(s):
        two = s[k:k + 2]
        if two in ("{{", "[["):
            depth += 1
            buf += two
            k += 2
        elif two in ("}}", "]]"):
            depth -= 1
            buf += two
            k += 2
        elif s[k] == "|" and depth == 0:
            parts.append(buf)
            buf = ""
            k += 1
        else:
            buf += s[k]
            k += 1
    parts.append(buf)

    params = {}
    for p in parts:
        if "=" not in p:
            continue
        key, val = p.split("=", 1)
        params[key.strip().lower()] = val.strip()
    return params


# ---------------------------------------------------------------------------
# Value parsers (all return None when nothing usable is found -- never guess)
# ---------------------------------------------------------------------------
def parse_length(v):
    """Height/spike/block -> cm (int). Handles convert templates, '1.95 m', '182 cm'."""
    if not v:
        return None
    m = re.search(r"\{\{convert\|\s*([\d.]+)\s*\|\s*(cm|m)\b", v, re.I)
    if m:
        num, unit = float(m.group(1)), m.group(2).lower()
        return round(num * 100) if unit == "m" else round(num)
    m = re.search(r"(\d{2,3})\s*cm", v, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d\.\d{1,2})\s*m\b", v)        # 1.95 m
    if m:
        return round(float(m.group(1)) * 100)
    m = re.search(r"^\s*(\d{3})\s*$", v)             # bare 3-digit number
    if m:
        return int(m.group(1))
    return None


def parse_weight(v):
    if not v:
        return None
    m = re.search(r"\{\{convert\|\s*(\d+)\s*\|\s*kg", v, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{2,3})\s*kg", v, re.I)
    if m:
        return int(m.group(1))
    return None


def parse_dob(v):
    """Any birth-date template/text -> DD/MM/YYYY string, else None.

    Handles {{birth date and age|YYYY|MM|DD}}, the hyphenated {{Birth-date...}}
    variant, and free-text dates like 'January 8, 1995' / '10 September 2003'.
    """
    if not v:
        return None
    m = re.search(r"\{\{\s*birth[- _]?date[^}]*\}\}", v, re.I)
    chunk = m.group(0) if m else v

    # Case 1: numeric |YYYY|MM|DD positional form
    nums = re.findall(r"\d+", chunk)
    for idx, n in enumerate(nums):
        if len(n) == 4:
            try:
                year, month, day = int(n), int(nums[idx + 1]), int(nums[idx + 2])
                if 1 <= month <= 12 and 1 <= day <= 31:
                    return f"{day:02d}/{month:02d}/{year:04d}"
            except (IndexError, ValueError):
                break

    # Case 2: free-text date inside the template/value -> let pandas parse it
    inner = re.sub(r"^\{\{[^|]*\|", "", chunk).strip("}{ ")
    inner = re.sub(r"\b(df|mf)\s*=\s*\w+\b", "", inner, flags=re.I).strip("| ")
    try:
        ts = pd.to_datetime(inner, errors="raise", dayfirst=False)
        return ts.strftime("%d/%m/%Y")
    except Exception:
        return None


def parse_club(v):
    """currentclub field -> plain club display name, stripping flagicons/markup."""
    if not v:
        return None
    v = re.sub(r"\{\{flagicon\|[^}]*\}\}", "", v, flags=re.I)
    m = re.search(r"\[\[([^\]]+)\]\]", v)
    if m:
        return split_link(m.group(1))[1]
    v = re.sub(r"\{\{[^}]*\}\}", "", v)            # drop any leftover templates
    v = re.sub(r"<[^>]+>", "", v).strip()
    return v or None


def map_position(abbr, infobox_pos):
    if abbr in POS_ABBR:
        return POS_ABBR[abbr]
    if infobox_pos:
        low = infobox_pos.lower()
        for key, num in POS_TEXT:
            if key in low:
                return num
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    rows = []
    issues = []                                   # players with no page / no infobox
    prov = {"height": {"infobox": 0, "roster": 0},
            "spike": {"infobox": 0, "roster": 0},
            "block": {"infobox": 0, "roster": 0}}

    for country, page in TEAMS.items():
        print(f"\n=== Layer 1: fetching roster -- {country} ===")
        wt = get_wikitext(page)
        time.sleep(DELAY)
        if not wt:
            print(f"   ! could not fetch team page: {page}")
            continue
        squad = parse_roster(extract_current_squad(wt))
        print(f"   found {len(squad)} players in current squad")

        for pl in squad:
            print(f"   Layer 2: {pl['name']}  <- {pl['page']}")
            pwt = get_wikitext(pl["page"])
            time.sleep(DELAY)

            height = spike = block = weight = dob = club = None
            ib_pos_text = None
            had_infobox = False

            if pwt is None:
                issues.append((country, pl["name"], "personal page not found"))
            else:
                ibtext = extract_infobox(pwt)
                if ibtext is None:
                    issues.append((country, pl["name"], "no volleyball infobox"))
                else:
                    had_infobox = True
                    ip = infobox_params(ibtext)
                    height = parse_length(ip.get("height", ""))
                    spike = parse_length(ip.get("spike", ""))
                    block = parse_length(ip.get("block", ""))
                    weight = parse_weight(ip.get("weight", ""))
                    dob = parse_dob(ip.get("birth_date", ""))
                    club = parse_club(ip.get("currentclub", ""))
                    ib_pos_text = ip.get("position", "")

            # provenance + roster fallback for the three key stats
            for field, ibval, rval in (
                ("height", height, pl["r_height"]),
                ("spike", spike, pl["r_spike"]),
                ("block", block, pl["r_block"]),
            ):
                if ibval is not None:
                    prov[field]["infobox"] += 1
                elif rval is not None:
                    prov[field]["roster"] += 1
            if height is None:
                height = pl["r_height"]
            if spike is None:
                spike = pl["r_spike"]
            if block is None:
                block = pl["r_block"]
            if dob is None:
                dob = pl["r_dob"]

            rows.append({
                "name": pl["name"],
                "date_of_birth": dob,
                "height": height,
                "weight": weight,
                "spike": spike,
                "block": block,
                "position_number": map_position(pl["pos_abbr"], ib_pos_text),
                "country": country,
                "club": club,
                # Phase 2 placeholders -- intentionally blank for every row
                "points_per_set": pd.NA,
                "blocks_per_set": pd.NA,
                "aces_per_set": pd.NA,
                "_had_infobox": had_infobox,
            })

    df = pd.DataFrame(rows)
    df.insert(0, "index", range(len(df)))

    out = "data/new_dataset_test.csv"
    df.drop(columns=["_had_infobox"]).to_csv(out, index=False, encoding="utf-8-sig")

    # ----------------------------- REPORT ----------------------------------
    n = len(df)
    print("\n" + "=" * 70)
    print("DATA QUALITY REPORT")
    print("=" * 70)
    print(f"Total players scraped (Turkey + Italy): {n}")
    by_country = df["country"].value_counts().to_dict()
    print("  by country:", ", ".join(f"{k}={v}" for k, v in by_country.items()))

    print("\nColumn completeness (filled / total):")
    report_cols = ["name", "date_of_birth", "height", "weight", "spike",
                   "block", "position_number", "country", "club",
                   "points_per_set", "blocks_per_set", "aces_per_set"]
    for c in report_cols:
        filled = df[c].notna().sum()
        bar = "#" * round(20 * filled / n) if n else ""
        print(f"  {c:18s} {filled:2d}/{n:<2d}  {bar}")

    print("\nKEY STATS -- where each value came from:")
    for field in ("height", "spike", "block"):
        ib = prov[field]["infobox"]
        ro = prov[field]["roster"]
        blank = n - ib - ro
        print(f"  {field:7s}: personal-page infobox={ib:2d}  "
              f"roster-table fallback={ro:2d}  still blank={blank:2d}")

    ib_count = df["_had_infobox"].sum()
    print(f"\nPersonal pages with a volleyball infobox: {ib_count}/{n}")

    print("\nPlayers with missing page or no infobox:")
    if issues:
        for ctry, name, why in issues:
            print(f"  - [{ctry}] {name}: {why}")
    else:
        print("  (none -- every player had a personal page with an infobox)")

    print("\n" + "=" * 70)
    print(f"FULL CSV CONTENTS  ({out})")
    print("=" * 70)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    print(df.drop(columns=["_had_infobox"]).to_string(index=False))
    print(f"\nSaved -> {out}")


if __name__ == "__main__":
    main()
