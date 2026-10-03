# Web dashboard

A tiny static page (`index.html`) that renders the front-contract fair value from
`data.json`, plus the build script and GitHub Action that refresh it.

```
web/
  index.html          # the dashboard (vanilla HTML/CSS/JS, no dependencies)
  data.json           # the latest snapshot (committed by the Action)
  build_fairvalue.py  # computes the snapshot
  vercel.json         # static-site config (clean URLs, no-cache for data.json)
```

## How it works

1. **GitHub Action** (`.github/workflows/update-fairvalue.yml`) runs after the
   US close, once the day's futures candle has settled (02:31 UTC, with a 05:31
   UTC backup, Mon–Fri close). Fair value is an end-of-day figure, so it prices
   the **front** ES contract for the **next session** off the close that just
   settled — never an intraday value, indexarb's overnight convention — with
   `web/build_fairvalue.py`, and commits `web/data.json` if it changed. (With
   GitHub's multi-hour scheduling delay, that slot executes ~06:30 UTC, after
   Yahoo finalises the futures candle, and still lands in the European morning.)
2. The commit triggers **Vercel** to redeploy the static page.
3. `index.html` fetches `data.json` and shows the fair value premium, the
   decomposition, and the observed future's rich/cheap signal.

Locally: `cd web && python -m http.server` then open <http://localhost:8000>.
Rebuild the snapshot by hand with `python web/build_fairvalue.py` (or pass
`--session YYYY-MM-DD --price-date YYYY-MM-DD`).

## Deploy to Vercel + a subdomain

1. Push this repo to GitHub and **merge to your default branch** (scheduled
   Actions only run on the default branch).
2. In Vercel → **Add New… → Project** → import the repo. Set:
   - **Root Directory**: `web`
   - **Framework Preset**: *Other* (it is a static site; no build step)
3. Deploy. You get a `*.vercel.app` URL.
4. **Subdomain**: at your DNS provider create the subdomain (e.g. `fv`) as a
   `CNAME` to `cname.vercel-dns.com`, then in Vercel → Project → **Settings →
   Domains** add `fv.yourdomain.com`. Vercel issues the TLS cert automatically.
5. Confirm the Action has push rights: repo → **Settings → Actions → General →
   Workflow permissions → Read and write**. Trigger a first run from the
   **Actions** tab (*Update fair value → Run workflow*).

After that, every weekday evening (after the US close) the snapshot refreshes
and Vercel redeploys — the page always shows the fair value for the next session.

> Educational tool, not investment advice. Reproduces the public index-arbitrage
> fair value methodology from free data; see the repository root for the model.
