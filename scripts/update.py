#!/usr/bin/env python3
"""
STRIKE_MAP Auto-Updater
========================
Scrapes conflict news from RSS feeds, processes with Gemini Flash (free),
updates index.html with new strikes and news items.

Runs via GitHub Actions every hour.
"""

import json
import re
import sys
import os
import hashlib
import datetime
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================

RSS_FEEDS = [
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"name": "Reuters World", "url": "https://www.rss-bridge.org/bridge01/?action=display&bridge=Reuters&feed=world&format=Atom"},
    {"name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml"},
    {"name": "CNN World", "url": "http://rss.cnn.com/rss/edition_world.rss"},
    {"name": "AP News", "url": "https://rsshub.app/apnews/topics/world-news"},
    {"name": "Iran Intl", "url": "https://www.iranintl.com/en/feed"},
    {"name": "Al Arabiya", "url": "https://english.alarabiya.net/tools/rss"},
    {"name": "Times of Israel", "url": "https://www.timesofisrael.com/feed/"},
    {"name": "Middle East Eye", "url": "https://www.middleeasteye.net/rss"},
]

CONFLICT_KEYWORDS = [
    "iran", "israel", "strike", "missile", "drone", "tehran", "idf",
    "hezbollah", "irgc", "khamenei", "centcom", "gulf", "kuwait",
    "bahrain", "qatar", "uae", "dubai", "saudi", "riyadh", "erbil",
    "iraq", "lebanon", "beirut", "epic fury", "casualties", "killed",
    "intercepted", "retaliation", "retaliatory", "bombing", "war",
    "pentagon", "trump iran", "pezeshkian", "strait of hormuz",
    "lng", "oil price", "tanker", "navy", "f-15", "patriot",
    "bandar abbas", "minab", "nuclear", "cluster munition",
    "embargo", "airspace closed", "refugee", "evacuation",
    "cyber attack", "ground troops", "reservists", "ceasefire",
]

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

DATA_DIR = Path(__file__).parent.parent / "data"
INDEX_HTML = Path(__file__).parent.parent / "index.html"
SEEN_FILE = DATA_DIR / "seen_hashes.json"
NEWS_FILE = DATA_DIR / "news.json"
STRIKES_FILE = DATA_DIR / "strikes.json"

# ============================================================
# RSS FETCHING
# ============================================================

def fetch_rss(url, timeout=15):
    """Fetch and parse RSS/Atom feed."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "StrikeMapBot/1.0 (conflict-tracker)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [WARN] Failed to fetch {url}: {e}")
        return None


def parse_feed(xml_text, source_name):
    """Parse RSS/Atom XML into list of articles."""
    articles = []
    if not xml_text:
        return articles

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return articles

    # Handle RSS 2.0
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        desc = (item.findtext("description") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        if title:
            articles.append({
                "title": title,
                "description": desc[:500],
                "link": link,
                "published": pub,
                "source": source_name,
            })

    # Handle Atom
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
        title = ""
        title_el = entry.find("atom:title", ns) or entry.find("{http://www.w3.org/2005/Atom}title")
        if title_el is not None:
            title = (title_el.text or "").strip()

        summary = ""
        sum_el = entry.find("atom:summary", ns) or entry.find("{http://www.w3.org/2005/Atom}summary")
        if sum_el is not None:
            summary = (sum_el.text or "").strip()

        link = ""
        link_el = entry.find("atom:link", ns) or entry.find("{http://www.w3.org/2005/Atom}link")
        if link_el is not None:
            link = link_el.get("href", "")

        updated = ""
        upd_el = entry.find("atom:updated", ns) or entry.find("{http://www.w3.org/2005/Atom}updated")
        if upd_el is not None:
            updated = (upd_el.text or "").strip()

        if title:
            articles.append({
                "title": title,
                "description": summary[:500],
                "link": link,
                "published": updated,
                "source": source_name,
            })

    return articles


def is_conflict_related(article):
    """Check if article is related to the Iran conflict."""
    text = f"{article['title']} {article['description']}".lower()
    matches = sum(1 for kw in CONFLICT_KEYWORDS if kw in text)
    return matches >= 2  # Need at least 2 keyword matches


def get_article_hash(article):
    """Generate unique hash for deduplication."""
    raw = f"{article['title'][:80]}".lower().strip()
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def load_seen_hashes():
    """Load previously seen article hashes."""
    if SEEN_FILE.exists():
        try:
            data = json.loads(SEEN_FILE.read_text())
            # Keep only last 7 days of hashes
            cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).isoformat()
            return {k: v for k, v in data.items() if v.get("seen_at", "") > cutoff}
        except:
            return {}
    return {}


def save_seen_hashes(hashes):
    """Save seen hashes."""
    SEEN_FILE.write_text(json.dumps(hashes, indent=2))


# ============================================================
# GEMINI FLASH PROCESSING
# ============================================================

def call_gemini(prompt, api_key):
    """Call Gemini Flash API."""
    url = f"{GEMINI_API_URL}?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
        }
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json"
    })

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw_response = resp.read().decode()
            print(f"  [DEBUG] Gemini API Status: {resp.status}")
            print(f"  [DEBUG] Raw API response length: {len(raw_response)} chars")

            result = json.loads(raw_response)

            # Check if response has expected structure
            if "candidates" not in result:
                print(f"  [ERROR] No 'candidates' in response: {raw_response[:500]}")
                return None
            if not result["candidates"]:
                print(f"  [ERROR] Empty candidates array: {raw_response[:500]}")
                return None

            text = result["candidates"][0]["content"]["parts"][0]["text"]
            print(f"  [DEBUG] Extracted text length: {len(text)} chars")
            return text
    except urllib.error.HTTPError as e:
        print(f"  [ERROR] HTTP {e.code}: {e.reason}")
        try:
            error_body = e.read().decode()
            print(f"  [ERROR] Response body: {error_body[:500]}")
        except:
            pass
        return None
    except Exception as e:
        print(f"  [ERROR] Gemini API call failed: {type(e).__name__}: {e}")
        return None


def process_articles_with_gemini(articles, api_key):
    """Send batch of articles to Gemini for structured extraction."""
    if not articles:
        return [], []

    articles_text = ""
    for i, a in enumerate(articles[:15]):  # Max 15 per batch
        articles_text += f"\n[{i+1}] SOURCE: {a['source']}\nTITLE: {a['title']}\nDESC: {a['description'][:300]}\nURL: {a['link']}\n"

    prompt = f"""You are a conflict intelligence analyst. Extract structured data from these news articles about the Iran-US-Israel war (Operation Epic Fury, started Feb 28 2026).

ARTICLES:
{articles_text}

Return ONLY valid JSON (no markdown, no backticks, no explanation) with this exact structure:
{{
  "news": [
    {{
      "headline": "Short headline under 80 chars",
      "summary": "2-3 sentence summary with key facts, numbers, sources",
      "source": "Source name",
      "cat": "strike|diplomacy|casualties|economic|military|humanitarian",
      "sev": "critical|high|medium",
      "time": "ISO 8601 UTC timestamp (best estimate)",
      "url": "article URL",
      "verified": true
    }}
  ],
  "strikes": [
    {{
      "t": "ISO timestamp",
      "f": "Attacker (e.g. IRGC Iran, IDF Israel, US Navy)",
      "to": "Target location/city",
      "ty": "Type (Missiles, Drones, Air Strike, Cruise Missiles)",
      "s": "hit|intercepted|partial",
      "l": "Brief label for strike",
      "w": 1-9 severity weight,
      "a": "Iran|Israel|US|Iran Proxy|other"
    }}
  ]
}}

RULES:
- Only extract genuinely NEW information (specific events, casualties, strikes)
- Skip opinion pieces, analysis, or rehashed old news
- Severity: critical = mass casualties/major escalation, high = significant, medium = notable
- If an article doesn't contain extractable strike/news data, skip it
- Be conservative — only include verified/sourced claims
- Return empty arrays if nothing new"""

    response = call_gemini(prompt, api_key)
    if not response:
        print("  [ERROR] No response from Gemini API")
        return [], []

    print(f"  [DEBUG] Gemini response preview: {response[:300]}...")

    try:
        # Clean response
        cleaned = response.strip()
        if cleaned.startswith("```"):
            print("  [DEBUG] Removing markdown code fences")
            cleaned = re.sub(r"^```(?:json)?\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)

        data = json.loads(cleaned)
        news_count = len(data.get("news", []))
        strikes_count = len(data.get("strikes", []))
        print(f"  [DEBUG] Parsed JSON successfully: {news_count} news, {strikes_count} strikes")
        return data.get("news", []), data.get("strikes", [])
    except json.JSONDecodeError as e:
        print(f"  [ERROR] Failed to parse Gemini response as JSON")
        print(f"  [ERROR] JSONDecodeError: {e}")
        print(f"  [ERROR] Full response ({len(response)} chars):")
        print(f"  {response[:1000]}")
        return [], []


# ============================================================
# FALLBACK: KEYWORD-BASED EXTRACTION (no AI needed)
# ============================================================

def extract_without_ai(articles):
    """Fallback: extract news items using keyword patterns."""
    news = []
    for a in articles:
        text = f"{a['title']} {a['description']}".lower()

        # Determine category
        cat = "military"
        if any(w in text for w in ["killed", "dead", "death toll", "casualties", "injured"]):
            cat = "casualties"
        elif any(w in text for w in ["strike", "missile", "drone", "bomb", "explosion"]):
            cat = "strike"
        elif any(w in text for w in ["negotiate", "diplomat", "ceasefire", "UN", "sanctions"]):
            cat = "diplomacy"
        elif any(w in text for w in ["oil", "gas", "lng", "market", "price", "airport", "flight"]):
            cat = "economic"
        elif any(w in text for w in ["refugee", "evacuation", "humanitarian", "civilian"]):
            cat = "humanitarian"

        # Determine severity
        sev = "medium"
        if any(w in text for w in ["killed", "dead", "critical", "emergency", "breaking"]):
            sev = "critical" if any(w in text for w in ["mass", "hundreds", "dozens", "major"]) else "high"

        news.append({
            "headline": a["title"][:80],
            "summary": a["description"][:250] if a["description"] else a["title"],
            "source": a["source"],
            "cat": cat,
            "sev": sev,
            "time": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "url": a["link"],
            "verified": True,
        })

    return news, []  # No strikes from keyword extraction


# ============================================================
# HTML UPDATER
# ============================================================

def load_existing_data():
    """Load existing news and strikes from JSON files."""
    news = []
    strikes = []
    if NEWS_FILE.exists():
        try:
            news = json.loads(NEWS_FILE.read_text())
        except:
            pass
    if STRIKES_FILE.exists():
        try:
            strikes = json.loads(STRIKES_FILE.read_text())
        except:
            pass
    return news, strikes


def save_data(news, strikes):
    """Save news and strikes to JSON files."""
    DATA_DIR.mkdir(exist_ok=True)
    NEWS_FILE.write_text(json.dumps(news, indent=2))
    STRIKES_FILE.write_text(json.dumps(strikes, indent=2))


def update_html(new_news, new_strikes):
    """Inject new news items and strikes into index.html."""
    if not INDEX_HTML.exists():
        print("[ERROR] index.html not found!")
        return False

    html = INDEX_HTML.read_text(encoding="utf-8")

    # Update version timestamp
    now = datetime.datetime.now(datetime.timezone.utc)
    ts = now.strftime("%b %d %H:%M UTC").upper()
    html = re.sub(
        r"<title>STRIKE_MAP // .*?</title>",
        f"<title>STRIKE_MAP // AUTO-UPDATE {ts}</title>",
        html
    )

    # === INSERT NEW NEWS ITEMS ===
    if new_news:
        news_js_items = []
        for n in new_news:
            # Properly escape for JavaScript by replacing quotes and backslashes
            headline = json.dumps(n.get("headline", ""))[1:-1]  # Remove surrounding quotes
            summary = json.dumps(n.get("summary", ""))[1:-1]
            source = json.dumps(n.get("source", ""))[1:-1]
            cat = n.get("cat", "military")
            sev = n.get("sev", "medium")
            time_str = n.get("time", now.isoformat() + "Z")
            url = json.dumps(n.get("url", "#"))[1:-1]

            news_js_items.append(
                f"  {{headline:'{headline}',summary:'{summary}',"
                f"source:'{source}',cat:'{cat}',sev:'{sev}',"
                f"time:'{time_str}',url:'{url}',verified:true}}"
            )

        news_block = ",\n".join(news_js_items)

        # Insert before the closing ]; of NEWS_ITEMS
        # Find the pattern: last news item followed by ];
        pattern = r"(let NEWS_ITEMS\s*=\s*\[[\s\S]*?)(];\s*\n\s*// =)"
        match = re.search(pattern, html)
        if match:
            insertion_point = match.start(2)
            html = html[:insertion_point] + "\n  // === AUTO-UPDATE " + ts + " ===\n" + news_block + ",\n" + html[insertion_point:]
            print(f"  [OK] Inserted {len(new_news)} news items")
        else:
            print("  [WARN] Could not find NEWS_ITEMS insertion point")

    # === INSERT NEW STRIKES ===
    if new_strikes:
        strike_js_items = []
        for s in new_strikes:
            # Properly escape for JavaScript
            t = json.dumps(s.get("t", now.isoformat() + "Z"))[1:-1]
            f_val = json.dumps(s.get("f", "Unknown"))[1:-1]
            to = json.dumps(s.get("to", "Unknown"))[1:-1]
            ty = json.dumps(s.get("ty", "Unknown"))[1:-1]
            status = json.dumps(s.get("s", "hit"))[1:-1]
            label = json.dumps(s.get("l", "Strike"))[1:-1]
            w = s.get("w", 5)
            a = json.dumps(s.get("a", "Unknown"))[1:-1]

            strike_js_items.append(
                f"  {{t:'{t}',f:'{f_val}',to:'{to}',ty:'{ty}',"
                f"s:'{status}',l:'{label}',w:{w},a:'{a}'}}"
            )

        strike_block = ",\n".join(strike_js_items)

        # Insert before the closing ]; of STRIKES
        pattern = r"(let STRIKES\s*=\s*\[[\s\S]*?)(];\s*\n\s*// News)"
        match = re.search(pattern, html)
        if not match:
            pattern = r"(let STRIKES\s*=\s*\[[\s\S]*?)(];\s*\n\s*let NEWS)"
            match = re.search(pattern, html)

        if match:
            insertion_point = match.start(2)
            html = html[:insertion_point] + "\n  // === AUTO-UPDATE STRIKES " + ts + " ===\n" + strike_block + ",\n" + html[insertion_point:]
            print(f"  [OK] Inserted {len(new_strikes)} strikes")
        else:
            print("  [WARN] Could not find STRIKES insertion point")

    # === UPDATE TICKER ===
    if new_news:
        critical_headlines = [n["headline"].upper() for n in new_news if n.get("sev") == "critical"][:6]
        if critical_headlines:
            ticker_text = " │ ".join(["🔴 " + critical_headlines[0]] + critical_headlines[1:])
            html = re.sub(
                r'(<div class="ticker-text" id="tickerText">)(.*?)(</div>)',
                r"\1" + ticker_text + r"\3",
                html
            )
            print(f"  [OK] Updated ticker with {len(critical_headlines)} headlines")

    INDEX_HTML.write_text(html, encoding="utf-8")
    return True


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print(f"STRIKE_MAP Auto-Updater — {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    use_ai = bool(gemini_key)

    if use_ai:
        print("[MODE] Gemini Flash AI processing")
    else:
        print("[MODE] Keyword extraction fallback (no API key found)")

    # Load seen hashes
    DATA_DIR.mkdir(exist_ok=True)
    seen = load_seen_hashes()
    print(f"[CACHE] {len(seen)} previously seen articles")

    # Fetch all RSS feeds
    all_articles = []
    for feed in RSS_FEEDS:
        print(f"\n[FETCH] {feed['name']}...")
        xml = fetch_rss(feed["url"])
        if xml:
            articles = parse_feed(xml, feed["name"])
            relevant = [a for a in articles if is_conflict_related(a)]
            print(f"  Found {len(articles)} articles, {len(relevant)} conflict-related")
            all_articles.extend(relevant)
        else:
            print(f"  Skipped (fetch failed)")

    # Deduplicate
    new_articles = []
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for a in all_articles:
        h = get_article_hash(a)
        if h not in seen:
            new_articles.append(a)
            seen[h] = {"seen_at": now_iso, "title": a["title"][:60]}

    print(f"\n[DEDUP] {len(new_articles)} new articles (filtered {len(all_articles) - len(new_articles)} duplicates)")

    if not new_articles:
        print("[DONE] No new articles. Exiting.")
        save_seen_hashes(seen)
        return

    # Process articles
    if use_ai:
        print(f"\n[AI] Processing {len(new_articles)} articles with Gemini Flash...")
        new_news, new_strikes = process_articles_with_gemini(new_articles, gemini_key)
    else:
        print(f"\n[KEYWORD] Processing {len(new_articles)} articles with keyword extraction...")
        new_news, new_strikes = extract_without_ai(new_articles)

    print(f"[RESULT] Extracted {len(new_news)} news items, {len(new_strikes)} strikes")

    if not new_news and not new_strikes:
        print("[DONE] No extractable data. Exiting.")
        save_seen_hashes(seen)
        return

    # Save to data files
    existing_news, existing_strikes = load_existing_data()
    all_news = existing_news + new_news
    all_strikes = existing_strikes + new_strikes

    # Keep last 200 news items and 150 strikes max
    all_news = all_news[-200:]
    all_strikes = all_strikes[-150:]
    save_data(all_news, all_strikes)

    # Update HTML
    print(f"\n[HTML] Updating index.html...")
    success = update_html(new_news, new_strikes)

    # Save seen hashes
    save_seen_hashes(seen)

    if success:
        print(f"\n[DONE] Successfully updated! {len(new_news)} news + {len(new_strikes)} strikes added.")
    else:
        print(f"\n[FAIL] HTML update failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
