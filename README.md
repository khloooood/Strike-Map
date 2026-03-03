# STRIKE_MAP v5.5 — Auto-Updating Conflict Tracker

Real-time Iran-US-Israel conflict tracker with cyberpunk UI. Auto-updates every hour via GitHub Actions + Gemini Flash (completely free).

**85 mapped strikes** · **117 verified news items** · **12 countries**

---

## Architecture

```
GitHub Actions (hourly cron)
    │
    ├── Scrape 9 RSS feeds (AJ, Reuters, BBC, CNN, AP, Iran Intl, etc.)
    ├── Filter conflict-related articles (keyword matching)
    ├── Deduplicate against seen_hashes.json
    ├── Process with Gemini Flash (free) → structured news + strikes
    │   └── Fallback: keyword extraction if no API key
    ├── Inject into index.html (news items, strikes, ticker)
    └── Auto-commit & push → GitHub Pages serves updated site
```

**Total cost: $0/month**

---

## Setup (5 minutes)

### 1. Create repo & push

```bash
git clone https://github.com/YOUR_USERNAME/strike-map.git
# OR upload all files via GitHub.com drag-and-drop
```

### 2. Get a free Gemini API key

1. Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Click **Create API Key** → Copy it

### 3. Add API key to GitHub Secrets

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
- Name: `GEMINI_API_KEY`
- Value: your key

### 4. Enable GitHub Pages

Repo → **Settings** → **Pages** → Source: `main` branch, `/ (root)` → **Save**

### 5. Enable GitHub Actions

Repo → **Actions** tab → Enable workflows

Site live at: `https://YOUR_USERNAME.github.io/strike-map/`

---

## File Structure

```
strike-map/
├── index.html                    # The map (GitHub Pages)
├── .nojekyll                     # Raw HTML serving
├── .github/workflows/
│   └── auto-update.yml           # Hourly cron
├── scripts/
│   └── update.py                 # Scraper + Gemini processor
└── data/
    ├── news.json                 # Accumulated news
    ├── strikes.json              # Accumulated strikes
    └── seen_hashes.json          # Dedup cache
```

## Manual trigger

Actions → Auto-Update Strike Map → Run workflow

## Troubleshooting

- **Action not running?** Check Actions tab enabled + GEMINI_API_KEY secret set
- **No new data?** RSS feeds may be down or all articles already seen. Delete `data/seen_hashes.json` to force re-process
- **Site not updating?** GitHub Pages takes 1-2 min. Hard refresh with Ctrl+Shift+R
