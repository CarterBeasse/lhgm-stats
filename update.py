"""
LHGM Junior C stats — leaderboard built from Spordle game sheets.

1. Reads game IDs from games.txt (one per line - see README for how to grab them).
2. For each game not already final, downloads its game sheet PDF.
3. If the sheet has been filled in (game played), stores it as final.
4. Rebuilds docs/index.html (the website) + docs/stats.json from all final sheets.

Run:  python update.py              (download new sheets + rebuild site)
      python update.py --offline    (just rebuild site from sheets/)
"""
import argparse
import html
import json
import re
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pypdf import PdfReader

# ---- config -----------------------------------------------------------------
PDF_URL = "https://pdf.play.spordle.com/game/{id}?locale=fr"
DIVISION_FILTER = ("Junior", "C")     # only count sheets whose division/class match
DELAY = 4                              # seconds between downloads - be polite

ROOT = Path(__file__).parent
GAMES_TXT = ROOT / "games.txt"
SHEETS = ROOT / "sheets"     # final (played) game sheets
DATA = ROOT / "data"
DOCS = ROOT / "docs"         # GitHub Pages serves this folder
STATE = DATA / "state.json"  # {"games": {id: "final"}}
MAX_ROWS = 30


# ---- download a sheet -------------------------------------------------------
class Blocked(Exception):
    pass


def fetch_sheet(gid):
    req = urllib.request.Request(PDF_URL.format(id=gid),
                                 headers={"User-Agent": "lhgm-stats (personal league stats page)"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code}")
        return None
    if body[:4] == b"%PDF":
        return body
    if b"<html" in body[:500].lower():
        raise Blocked("got a web page instead of a PDF (security checkpoint)")
    return None


# ---- 3. parse a sheet -------------------------------------------------------
def fields(src):
    reader = PdfReader(src)
    return {k: str(v.get("/V") or "").strip() for k, v in (reader.get_fields() or {}).items()}


def is_played(f):
    """Counts once it's been completed: rosters entered AND (end time or final score).
    Future sheets come pre-filled with a 0-0 score but no players, so require a roster."""
    has_roster = any(f.get(f"playerName{side}{i}") for side in ("Vis", "Loc") for i in range(1, MAX_ROWS))
    return has_roster and bool(f.get("gameEnd") or (f.get("scoreVis") and f.get("scoreLoc")))


def clean_name(name):
    return re.sub(r"\s*\*\s*$", "", name).strip().title()


def parse_sheet(f, gid):
    game = {"id": gid, "date": f.get("gameDate", ""), "division": f.get("divisionName", ""),
            "class": f.get("className", ""), "teams": {}}
    for side in ("Vis", "Loc"):
        roster = {}
        for i in range(1, MAX_ROWS):
            num, name = f.get(f"playerNum{side}{i}"), f.get(f"playerName{side}{i}")
            if num and name:
                roster[num] = clean_name(name)
        goalies = {}
        for i in range(1, 4):
            num, name = f.get(f"goalerNum{side}{i}"), f.get(f"goalerName{side}{i}")
            if num and name:
                goalies[num] = clean_name(name)
        scorer_key = "scorerVis" if side == "Vis" else "scoreLoc"   # Spordle's field names
        goals = []
        for i in range(1, MAX_ROWS):
            s = f.get(f"{scorer_key}{i}")
            if s:
                goals.append({"g": s, "a": [a for a in (f.get(f"assistOne{side}{i}"),
                                                        f.get(f"assistTwo{side}{i}")) if a]})
        pims = [f.get(f"minorPen{side}Num{i}") for i in range(1, MAX_ROWS)
                if f.get(f"minorPen{side}Code{i}")]
        game["teams"][side] = {"name": f.get(f"TeamName{side}", ""), "roster": roster,
                               "goalies": goalies, "goals": goals, "pims": pims,
                               "score": f.get(f"score{side}", "")}
    return game


# ---- 4. build stats + site --------------------------------------------------
def build_stats(games):
    stats = defaultdict(lambda: {"GP": 0, "G": 0, "A": 0, "PIM": 0})
    warnings = []
    for game in games:
        for t in game["teams"].values():
            everyone = {**t["roster"], **t["goalies"]}

            def key(num):
                if num in everyone:
                    return (everyone[num], t["name"])
                warnings.append(f'game {game["id"]}: #{num} not on {t["name"]} roster')

            for name in t["roster"].values():
                stats[(name, t["name"])]["GP"] += 1
            for goal in t["goals"]:
                if (k := key(goal["g"])):
                    stats[k]["G"] += 1
                for a in goal["a"]:
                    if (k := key(a)):
                        stats[k]["A"] += 1
            for num in t["pims"]:
                if num not in ("", "-") and (k := key(num)):
                    stats[k]["PIM"] += 2
    rows = [{"player": n, "team": tm, **s, "PTS": s["G"] + s["A"]} for (n, tm), s in stats.items()]
    rows.sort(key=lambda r: (-r["PTS"], -r["G"], r["GP"], r["player"]))
    return rows, warnings


def build_site(rows, games):
    DOCS.mkdir(exist_ok=True)
    updated = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    teams = sorted({r["team"] for r in rows})
    (DOCS / "stats.json").write_text(json.dumps(
        {"updated": updated, "games": len(games), "players": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    body = "\n".join(
        f'<tr data-team="{html.escape(r["team"])}"><td class="rk">{i}</td>'
        f'<td class="pl">{html.escape(r["player"])}<small>{html.escape(r["team"])}</small></td><td class="tm">{html.escape(r["team"])}</td>'
        f'<td>{r["GP"]}</td><td>{r["G"]}</td><td>{r["A"]}</td><td class="pts">{r["PTS"]}</td>'
        f'<td>{r["PIM"]}</td></tr>'
        for i, r in enumerate(rows, 1))
    opts = "".join(f'<option>{html.escape(t)}</option>' for t in teams)

    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LHGM Junior C Stats</title>
<style>
:root{{--bg:#0b1220;--card:#121a2b;--line:#1f2a40;--txt:#e8edf5;--mut:#8b97ab;--acc:#e23b3b;--blue:#7fb0ff}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--txt);font:15px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
header{{padding:20px 16px 8px;max-width:900px;margin:auto}}
h1{{margin:0;font-size:1.4rem;letter-spacing:.3px}} h1 span{{color:var(--acc)}}
.sub{{color:var(--mut);font-size:.85rem;margin-top:4px}}
.bar{{display:flex;gap:8px;flex-wrap:wrap;max-width:900px;margin:12px auto;padding:0 16px}}
input,select{{flex:1;min-width:160px;padding:9px 10px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--txt);font:inherit}}
.wrap{{max-width:900px;margin:0 auto 32px;padding:0 16px;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:10px;overflow:hidden}}
th,td{{padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap;text-align:right}}
th{{background:#17213a;color:var(--blue);cursor:pointer;user-select:none;font-weight:600;position:sticky;top:0}}
th.l,td.pl,td.tm{{text-align:left}} td.rk{{color:var(--mut);text-align:left}} td.tm{{color:var(--mut);font-size:.85rem}}
td.pts{{font-weight:700}} tbody tr:nth-child(-n+3) td.pts{{color:var(--acc)}}
tr:hover td{{background:#18233a}} td.pl small{{display:none}}
@media(max-width:620px){{th.tmh,td.tm{{display:none}} td.pl small{{display:block;color:var(--mut);font-size:.72rem}}
 th,td{{padding:7px 6px}} td.pl{{white-space:normal}}}}
</style></head><body>
<header><h1>LHGM <span>Junior C</span> — Marqueurs</h1>
<div class="sub">{len(games)} matchs · mis à jour {updated} · cliquer une colonne pour trier</div></header>
<div class="bar"><input id="q" placeholder="Chercher un joueur…">
<select id="team"><option value="">Toutes les équipes</option>{opts}</select></div>
<div class="wrap"><table><thead><tr>
<th class="l">#</th><th class="l" data-c="1">Joueur</th><th class="l tmh" data-c="2">Équipe</th>
<th data-c="3">PJ</th><th data-c="4">B</th><th data-c="5">A</th><th data-c="6">PTS</th><th data-c="7">PUN</th>
</tr></thead><tbody>
{body}
</tbody></table></div>
<script>
const tb=document.querySelector('tbody'),q=document.getElementById('q'),tm=document.getElementById('team');
function filt(){{const s=q.value.toLowerCase(),t=tm.value;let n=0;
 for(const r of tb.rows){{const ok=(!t||r.dataset.team===t)&&r.cells[1].textContent.toLowerCase().includes(s);
  r.style.display=ok?'':'none'; if(ok) r.cells[0].textContent=++n;}}}}
q.oninput=filt; tm.onchange=filt;
document.querySelectorAll('th[data-c]').forEach(th=>th.onclick=()=>{{const c=+th.dataset.c,num=c>2;
 [...tb.rows].sort((a,b)=>{{const x=a.cells[c].textContent,y=b.cells[c].textContent;
  return num?(y-x)||(b.cells[6].textContent-a.cells[6].textContent):x.localeCompare(y)}})
 .forEach(r=>tb.appendChild(r)); filt();}});
</script></body></html>"""
    (DOCS / "index.html").write_text(page, encoding="utf-8")


# ---- main -------------------------------------------------------------------
def read_game_ids():
    if not GAMES_TXT.exists():
        return []
    return sorted({m for m in re.findall(r"\d{5,}", GAMES_TXT.read_text(encoding="utf-8"))})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    SHEETS.mkdir(exist_ok=True)
    DATA.mkdir(exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {"games": {}}
    for pdf in SHEETS.glob("*.pdf"):          # re-check saved sheets; drop any that aren't played
        if is_played(fields(pdf)):
            state["games"][pdf.stem] = "final"
        else:
            pdf.unlink()
            state["games"][pdf.stem] = "pending"

    if not args.offline:
        today = datetime.now().strftime("%Y-%m-%d")
        dates = state.setdefault("dates", {})   # game date, learned from its sheet
        todo = [g for g in read_game_ids() if state["games"].get(g) != "final"
                and dates.get(g, "0000")[:10] <= today]   # skip games that haven't happened yet
        print(f"{len(todo)} games to check")
        for gid in todo:
            try:
                pdf = fetch_sheet(gid)
            except Blocked as e:
                print(f"  stopped: Spordle blocked the download ({e}).")
                print("  -> save the remaining PDFs into sheets/ by hand and run with --offline")
                break
            time.sleep(DELAY)
            if not pdf:
                print(f"  {gid}: no sheet")
                continue
            tmp = SHEETS / f"{gid}.pdf.tmp"
            tmp.write_bytes(pdf)
            f = fields(tmp)
            dates[gid] = f.get("gameDate", "")
            if is_played(f):
                tmp.replace(SHEETS / f"{gid}.pdf")
                state["games"][gid] = "final"
                print(f"  {gid}: sheet posted ✓")
            else:
                tmp.unlink()
                print(f"  {gid}: not played yet")
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True))

    games = []
    for pdf in sorted(SHEETS.glob("*.pdf")):
        f = fields(pdf)
        if not is_played(f):
            continue
        g = parse_sheet(f, pdf.stem)
        if DIVISION_FILTER and (g["division"], g["class"]) != DIVISION_FILTER:
            continue
        games.append(g)

    rows, warnings = build_stats(games)
    build_site(rows, games)
    for w in warnings:
        print("  warning:", w)
    print(f"\nsite rebuilt from {len(games)} games -> docs/index.html")
    for r in rows[:10]:
        print(f'  {r["player"][:24]:25}{r["team"][:26]:27}{r["GP"]:>3}{r["G"]:>3}{r["A"]:>3}{r["PTS"]:>4}')


if __name__ == "__main__":
    main()