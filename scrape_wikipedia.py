"""
Wikipedia volleyball roster scraper -- FULL RUN (7 women's national teams).

Teams: Turkey, Italy, France, Poland, Germany, USA, Brazil.

Rebuilds a fresh, accurate player dataset from Wikipedia (CC-licensed; factual
stats are not copyrightable). Validated on a Turkey+Italy test (see
scrape_wikipedia_test.py) before scaling here.

Two-layer scrape:
  Layer 1 -- national team page "Current squad": player list (+ sometimes stats).
             Formats handled: wikitable (abbr/text/no position, [[link]] or
             {{sortname}}), bulleted list, and {{#section}} transclusion of the
             shared Olympics-rosters page (France, Poland).
  Layer 2 -- each player's personal page infobox: height, spike, block, weight,
             DOB, club. CANONICAL: when infobox and roster disagree, infobox wins.

Politeness: clear User-Agent, ~1.5s delay between requests, no hammering.

Output: data/new_dataset.csv  (does NOT touch clean_data.csv or app.py).
Dates are written as DD/MM/YYYY to match the existing app schema.
"""

import re
import sys
import time
import requests
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

API = "https://en.wikipedia.org/w/api.php"
HEADERS = {
    "User-Agent": "VolleyballScoutingBot/1.0 (educational project)"
}
DELAY = 1.5  # seconds between page requests -- be polite to Wikipedia

# display country name -> English Wikipedia national-team page title
TEAMS = {
    "Turkey": "Turkey women's national volleyball team",
    "Italy": "Italy women's national volleyball team",
    "France": "France women's national volleyball team",
    "Poland": "Poland women's national volleyball team",
    "Germany": "Germany women's national volleyball team",
    "USA": "United States women's national volleyball team",
    "Brazil": "Brazil women's national volleyball team",
}

# Position abbreviation -> existing app numeric scheme
# 1=Setter 2=Opposite 3=Middle Blocker 4=Outside Hitter 6=Libero
POS_ABBR = {"S": 1, "OP": 2, "OS": 2, "MB": 3, "OH": 4, "WS": 4, "L": 6}
# free-text fallback (checked in order; first hit wins)
POS_TEXT = [
    ("libero", 6),
    ("setter", 1),
    ("middle", 3),
    ("outside", 4),
    ("wing spiker", 4),
    ("opposite", 2),
]

# Manual corrections applied after scraping (player name -> {field: value})
CORRECTIONS = {
    "Eylül Yatgın": {"club": "Vakıfbank"},
    "Derya Cebecioğlu": {"club": "Beşiktaş"},
}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def get_wikitext(page):
    """Return raw wikitext for a page (following redirects), or None if missing."""
    params = {"action": "parse", "page": page, "prop": "wikitext",
              "format": "json", "redirects": 1}
    try:
        data = requests.get(API, params=params, headers=HEADERS, timeout=30).json()
    except Exception as e:
        print(f"   ! request failed for {page!r}: {e}", file=sys.stderr)
        return None
    if "parse" not in data:
        return None
    return data["parse"]["wikitext"]["*"]


# ---------------------------------------------------------------------------
# Low-level wikitext helpers
# ---------------------------------------------------------------------------
def split_link(link):
    """[[Target|Display]] content -> (page_title, display_name)."""
    if "|" in link:
        target, disp = link.split("|", 1)
        return target.strip(), disp.strip()
    return link.strip(), link.strip()


def strip_cell_attr(cell):
    """Drop a leading table-cell attribute (e.g. 'align=left|', 'style=\"..\"|')."""
    depth = 0
    i = 0
    while i < len(cell):
        two = cell[i:i + 2]
        if two in ("{{", "[["):
            depth += 1
            i += 2
            continue
        if two in ("}}", "]]"):
            depth -= 1
            i += 2
            continue
        if cell[i] == "|" and depth == 0:
            if "=" in cell[:i]:
                return cell[i + 1:].strip()
            return cell.strip()
        i += 1
    return cell.strip()


def extract_name(cell):
    """Name cell -> (page_title, display_name). Handles [[link]], {{sortname}}, text."""
    cell = strip_cell_attr(cell)
    m = re.search(r"\[\[([^\]]+)\]\]", cell)
    if m:
        return split_link(m.group(1))
    m = re.search(r"\{\{sortname\|([^|}]+)\|([^|}]+)((?:\|[^}]*)?)\}\}", cell, re.I)
    if m:
        first, last = m.group(1).strip(), m.group(2).strip()
        full = f"{first} {last}"
        page = full
        for p in m.group(3).strip("|").split("|"):
            p = p.strip()
            if p and "=" not in p and "nolink" not in p.lower():
                page = p          # 3rd positional param = disambiguated article title
                break
        return page, full
    txt = re.sub(r"<[^>]+>", "", cell).strip()
    return txt, txt


def position_token(cell):
    """Extract a position abbreviation or phrase from a roster cell."""
    if not cell:
        return ""
    m = re.search(r"\{\{(?:abbr|tooltip)\|([^|}]+)\|", cell, re.I)
    if m:
        return m.group(1).strip()
    t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", cell)   # links -> display
    t = re.sub(r"\{\{[^}]*\}\}", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    return t.strip()


def map_position(raw):
    if not raw:
        return None
    token = raw.strip()
    if token.upper() in POS_ABBR:
        return POS_ABBR[token.upper()]
    low = token.lower()
    for key, num in POS_TEXT:
        if key in low:
            return num
    return None


# ---------------------------------------------------------------------------
# Section / roster extraction
# ---------------------------------------------------------------------------
def extract_current_squad(wt):
    # stop at the NEXT heading of any level (\n== matches both == and ===),
    # so we don't sweep "Previous squads" / "Coach history" tables that follow.
    m = re.search(r"==+\s*Current squad\s*==+(.*?)(?=\n==)", wt, re.S | re.I)
    if not m:
        m = re.search(r"==+\s*(?:Squad|Team roster|Roster)\s*==+(.*?)(?=\n==)",
                      wt, re.S | re.I)
    return m.group(1) if m else ""


def resolve_transclusion(section):
    """If the squad section transcludes a labelled section, fetch and return it."""
    m = re.search(r"\{\{#(?:section|lst):([^|]+)\|([^}]+)\}\}", section, re.I)
    if not m:
        return None
    page, label = m.group(1).strip(), m.group(2).strip()
    print(f"   (resolving transclusion -> {page} [section {label}])")
    wt = get_wikitext(page)
    time.sleep(DELAY)
    if not wt:
        return None
    sm = re.search(r'<section\s+begin\s*=\s*"?' + re.escape(label) +
                   r'"?\s*/?>(.*?)<section\s+end', wt, re.S | re.I)
    return sm.group(1) if sm else None


def row_cells(row):
    """Split a wikitable row into cells (handles both `||` and newline `|` styles)."""
    cells = []
    for line in row.split("\n"):
        s = line.strip()
        if not s.startswith("|"):
            continue
        if s[:2] in ("|-", "|}", "|+"):
            continue
        s = s[1:]
        cells.extend(part.strip() for part in s.split("||"))
    return cells


def header_index(header_cells, *keywords):
    for i, c in enumerate(header_cells):
        cl = c.lower()
        if any(k in cl for k in keywords):
            return i
    return None


def parse_table(section):
    """General wikitable roster parser (header-driven, column order independent)."""
    # header = the `!`-prefixed lines preceding the first data row
    header_block = []
    for line in section.splitlines():
        s = line.strip()
        if s.startswith("!"):
            header_block.append(s)
        elif s.startswith("|-") and header_block:
            break
    hcells = []
    for line in header_block:
        for part in re.split(r"!!|\|\|", line.lstrip("!")):
            hcells.append(part.strip())

    i_name = header_index(hcells, "name", "player")
    i_pos = header_index(hcells, "pos")
    i_h = header_index(hcells, "height")
    i_sp = header_index(hcells, "spike")
    i_bl = header_index(hcells, "block")
    i_w = header_index(hcells, "weight")
    i_dob = header_index(hcells, "birth", "date of birth")
    i_club = header_index(hcells, "club")

    players = []
    for row in re.split(r"\n\|-", section):
        if "!" in row and "||" not in row and "[[" not in row and "sortname" not in row:
            continue
        cells = row_cells(row)
        if not cells:
            continue

        def cell(i):
            return cells[i] if (i is not None and i < len(cells)) else ""

        name_cell = cell(i_name)
        if not (("[[" in name_cell) or ("sortname" in name_cell.lower())):
            # fall back: scan any cell for a player reference
            name_cell = next((c for c in cells
                              if "[[" in c or "sortname" in c.lower()), "")
        if not name_cell:
            continue
        page, name = extract_name(name_cell)
        if not name or len(name) < 2:
            continue

        players.append({
            "page": page, "name": name,
            "pos": map_position(position_token(cell(i_pos))),
            "r_height": parse_length(strip_cell_attr(cell(i_h))),
            "r_spike": parse_length(strip_cell_attr(cell(i_sp))),
            "r_block": parse_length(strip_cell_attr(cell(i_bl))),
            "r_weight": parse_weight(strip_cell_attr(cell(i_w))),
            "r_dob": parse_dob(strip_cell_attr(cell(i_dob))),
            "r_club": parse_club(strip_cell_attr(cell(i_club))),
        })
    return players


def parse_list(section):
    """Bulleted-list roster parser ('* 3 [[Name]] (S)' or '... {{Tooltip|OH|..}}')."""
    players = []
    for line in section.splitlines():
        s = line.strip()
        if not s.startswith("*") or s.startswith("**"):
            continue
        lm = re.search(r"\[\[([^\]]+)\]\]", s)        # first link = player
        if not lm:
            continue
        page, name = split_link(lm.group(1))
        pm = re.search(r"\{\{(?:tooltip|abbr)\|([^|}]+)\|", s, re.I)
        if pm:
            pos = pm.group(1).strip()
        else:
            pp = re.search(r"\(([A-Za-z/]{1,3})\)", s)   # trailing plain "(S)"
            pos = pp.group(1).strip() if pp else ""
        players.append({
            "page": page, "name": name, "pos": map_position(pos),
            "r_height": None, "r_spike": None, "r_block": None,
            "r_weight": None, "r_dob": None, "r_club": None,
        })
    return players


def parse_roster(section):
    transcluded = resolve_transclusion(section)
    if transcluded:
        section = transcluded
    if "{|" in section:
        players = parse_table(section)
        if players:
            return players
    return parse_list(section)


# ---------------------------------------------------------------------------
# Infobox extraction + value parsers
# ---------------------------------------------------------------------------
def extract_infobox(wt):
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
    s = infobox[2:-2]
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
        if "=" in p:
            key, val = p.split("=", 1)
            params[key.strip().lower()] = val.strip()
    return params


def parse_length(v):
    """Height/spike/block -> cm (int). Handles convert templates, '1.95 m',
    '1,94 m' (comma decimal), '182 cm', bare 3-digit."""
    if not v:
        return None
    m = re.search(r"\{\{convert\|\s*([\d.]+)\s*\|\s*(cm|m)\b", v, re.I)
    if m:
        num, unit = float(m.group(1)), m.group(2).lower()
        return round(num * 100) if unit == "m" else round(num)
    m = re.search(r"(\d{2,3})\s*cm", v, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d)[.,](\d{1,2})\s*m\b", v)        # 1.95 m / 1,94 m
    if m:
        return round(float(f"{m.group(1)}.{m.group(2)}") * 100)
    m = re.search(r"^\s*(\d{3})\s*$", v)
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
    """Birth-date template/text -> DD/MM/YYYY string, else None."""
    if not v:
        return None
    m = re.search(r"\{\{\s*birth[- _]?date[^}]*\}\}", v, re.I)
    chunk = m.group(0) if m else v
    nums = re.findall(r"\d+", chunk)
    for idx, n in enumerate(nums):
        if len(n) == 4:
            try:
                year, month, day = int(n), int(nums[idx + 1]), int(nums[idx + 2])
                if 1 <= month <= 12 and 1 <= day <= 31:
                    return f"{day:02d}/{month:02d}/{year:04d}"
            except (IndexError, ValueError):
                break
    inner = re.sub(r"^\{\{[^|]*\|", "", chunk).strip("}{ ")
    inner = re.sub(r"\b(df|mf)\s*=\s*\w+\b", "", inner, flags=re.I).strip("| ")
    try:
        return pd.to_datetime(inner, errors="raise").strftime("%d/%m/%Y")
    except Exception:
        return None


def _clean_club(name):
    name = re.sub(r"<ref.*", "", name, flags=re.I | re.S)
    name = re.sub(r"<[^>]+>", "", name)
    return name.strip(" []{}<>|").strip() or None


def parse_club(v):
    if not v:
        return None
    v = re.sub(r"\{\{flagicon\|[^}]*\}\}", "", v, flags=re.I)
    m = re.search(r"\[\[([^\]]+)\]\]", v)
    if m:
        return _clean_club(split_link(m.group(1))[1])   # e.g. fixes 'VakıfBank[' typo
    v = re.sub(r"\{\{[^}]*\}\}", "", v)
    return _clean_club(v)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    rows = []
    issues = []
    prov = {f: {"infobox": 0, "roster": 0} for f in ("height", "spike", "block")}

    for country, page in TEAMS.items():
        print(f"\n=== Layer 1: roster -- {country} ===")
        wt = get_wikitext(page)
        time.sleep(DELAY)
        if not wt:
            print(f"   ! could not fetch team page: {page}")
            continue
        squad = parse_roster(extract_current_squad(wt))
        print(f"   found {len(squad)} players")

        for pl in squad:
            print(f"   Layer 2: {pl['name']}  <- {pl['page']}")
            pwt = get_wikitext(pl["page"])
            time.sleep(DELAY)

            height = spike = block = weight = dob = club = None
            ib_pos = None
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
                    ib_pos = ip.get("position", "")

            # provenance (personal page wins; roster only fills gaps)
            for field, ibval, rval in (("height", height, pl["r_height"]),
                                       ("spike", spike, pl["r_spike"]),
                                       ("block", block, pl["r_block"])):
                if ibval is not None:
                    prov[field]["infobox"] += 1
                elif rval is not None:
                    prov[field]["roster"] += 1
            height = height if height is not None else pl["r_height"]
            spike = spike if spike is not None else pl["r_spike"]
            block = block if block is not None else pl["r_block"]
            weight = weight if weight is not None else pl["r_weight"]
            dob = dob if dob is not None else pl["r_dob"]
            club = club if club is not None else pl["r_club"]
            # position: roster abbreviation is cleaner; infobox text is fallback
            position = pl["pos"] if pl["pos"] is not None else map_position(ib_pos)

            rows.append({
                "name": pl["name"], "date_of_birth": dob, "height": height,
                "weight": weight, "spike": spike, "block": block,
                "position_number": position, "country": country, "club": club,
                "points_per_set": pd.NA, "blocks_per_set": pd.NA, "aces_per_set": pd.NA,
                "_had_infobox": had_infobox,
            })

    df = pd.DataFrame(rows)

    # --- manual corrections (transfers) ------------------------------------
    applied = []
    for name, fields in CORRECTIONS.items():
        mask = df["name"] == name
        if mask.any():
            for col, val in fields.items():
                df.loc[mask, col] = val
            applied.append(name)
        else:
            applied.append(f"{name} (NOT FOUND)")

    # --- dedup by name (safety net) ----------------------------------------
    before = len(df)
    df = df.drop_duplicates("name", keep="first").reset_index(drop=True)
    dup_removed = before - len(df)

    df.insert(0, "index", range(len(df)))
    out = "data/new_dataset.csv"
    df.drop(columns=["_had_infobox"]).to_csv(out, index=False, encoding="utf-8-sig")

    # ----------------------------- REPORT ----------------------------------
    n = len(df)
    print("\n" + "=" * 72)
    print("DATA QUALITY REPORT")
    print("=" * 72)
    print(f"Total players (after dedup): {n}   (duplicates removed: {dup_removed})")
    print("Per-country breakdown:")
    for k, v in df["country"].value_counts().reindex(TEAMS.keys()).dropna().items():
        print(f"   {k:8s} {int(v)}")

    print("\nColumn completeness (filled / total):")
    for c in ["name", "date_of_birth", "height", "weight", "spike", "block",
              "position_number", "country", "club",
              "points_per_set", "blocks_per_set", "aces_per_set"]:
        filled = df[c].notna().sum()
        bar = "#" * round(20 * filled / n) if n else ""
        print(f"   {c:18s} {filled:2d}/{n:<2d}  {bar}")

    print("\nKEY STATS -- source of each value:")
    for f in ("height", "spike", "block"):
        ib, ro = prov[f]["infobox"], prov[f]["roster"]
        print(f"   {f:7s}: infobox={ib:2d}  roster-fallback={ro:2d}  "
              f"blank={n - ib - ro:2d}")

    miss_sp = df[df["spike"].isna()]
    miss_bl = df[df["block"].isna()]
    miss_any = df[df["spike"].isna() | df["block"].isna()]
    print(f"\nMissing spike: {len(miss_sp)}   Missing block: {len(miss_bl)}   "
          f"Missing spike and/or block: {len(miss_any)}")
    print("   clustering by country (missing spike OR block):")
    for k, v in miss_any["country"].value_counts().items():
        names = ", ".join(miss_any[miss_any["country"] == k]["name"])
        print(f"     {k}: {v}  -> {names}")

    print("\nManual corrections applied:", ", ".join(applied))

    print("\nPlayers with missing page or no infobox:")
    if issues:
        for ctry, name, why in issues:
            print(f"   - [{ctry}] {name}: {why}")
    else:
        print("   (none)")

    # --- automated sanity flags --------------------------------------------
    print("\nSUSPICIOUS VALUES TO EYEBALL:")
    flags = []
    for _, r in df.iterrows():
        h, sp, bl = r["height"], r["spike"], r["block"]
        if pd.notna(h) and (h < 160 or h > 210):
            flags.append(f"{r['name']} ({r['country']}): height {h} cm out of range")
        if pd.notna(bl) and pd.notna(h) and bl < h:
            flags.append(f"{r['name']} ({r['country']}): block {bl} < height {h}")
        if pd.notna(sp) and pd.notna(bl) and sp < bl:
            flags.append(f"{r['name']} ({r['country']}): spike {sp} < block {bl}")
        if pd.notna(bl) and pd.notna(h) and (bl - h) < 40:
            flags.append(f"{r['name']} ({r['country']}): low block reach "
                         f"(block {bl} - height {h} = {bl - h})")
        if pd.notna(sp) and pd.notna(bl) and (sp - bl) > 45:
            flags.append(f"{r['name']} ({r['country']}): implausible spike-block "
                         f"gap (spike {sp} - block {bl} = {sp - bl}); likely bad "
                         f"block value on Wikipedia")
        if pd.isna(r["position_number"]):
            flags.append(f"{r['name']} ({r['country']}): position unmapped")
    if flags:
        for f in flags:
            print("   ! " + f)
    else:
        print("   (none)")

    print("\n" + "=" * 72)
    print(f"FULL CSV CONTENTS  ({out})")
    print("=" * 72)
    pd.set_option("display.max_rows", None)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)
    print(df.drop(columns=["_had_infobox"]).to_string(index=False))
    print(f"\nSaved -> {out}")


if __name__ == "__main__":
    main()
