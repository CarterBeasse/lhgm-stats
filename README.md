# LHGM Junior C Stats

Auto-updating points leaderboard (GP, G, A, PTS, PIM) built from Spordle game sheets.

## Run locally
```
pip install pypdf playwright
python -m playwright install chromium
python update.py            # scrape schedule, grab new sheets, rebuild docs/index.html
python update.py --headed   # same, but watch the browser
python update.py --offline  # just rebuild the site from sheets/
```

## Put it online (free, updates itself)
1. Create a GitHub repo and push this folder.
2. Repo → Settings → Pages → Source: "Deploy from a branch", branch `main`, folder `/docs`.
3. Repo → Actions → "Update stats" → Run workflow (first run). After that it runs every morning.

Site URL: `https://<your-username>.github.io/<repo-name>/`

## How it works
- `update.py` opens the Junior C schedule in headless Chrome and collects every game ID.
- For each game not already final it downloads `pdf.play.spordle.com/game/<id>`.
- If the sheet is filled in (final score/end time), it's saved to `sheets/` and never re-downloaded.
- Stats are rebuilt from every sheet in `sheets/` (filtered to Junior C).

If a sheet ever fails to download, drop the PDF into `sheets/` manually and run `--offline`.
