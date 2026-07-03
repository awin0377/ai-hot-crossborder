#!/usr/bin/env python3
"""
AI HOT 跨境出海专能版 — 自动生成脚本
Fetches aihot daily report + selected items, filters for cross-border relevance,
generates a single-file HTML dashboard.

Runs in GitHub Actions daily. Zero local dependencies. Python 3.11+ stdlib only.
"""

import json
import urllib.request
import urllib.error
import re
import sys
import os
from datetime import datetime, timezone, timedelta
from html import escape as html_escape

# ── Config ──────────────────────────────────────────────────────────────────
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
AIHOT_BASE = "https://aihot.virxact.com"
BEIJING_TZ = timezone(timedelta(hours=8))
MAX_PER_SECTION = 8
SUMMARY_MAX_CHARS = 60

# ── Section definitions ─────────────────────────────────────────────────────
SECTIONS = [
    {
        "id": "s1",
        "icon": "\U0001f916",
        "title": "\u7248\u57571 \u00b7 B2B\u81ea\u52a8\u5316\u83b7\u5ba2\u4e0e\u51fa\u6d77\u5de5\u5177",
        "nav_label": "B2B\u83b7\u5ba2\u5de5\u5177",
        "keywords": [
            "agent", "\u81ea\u52a8\u5316", "crm", "\u83b7\u5ba2", "\u5916\u8d38", "b2b",
            "\u8868\u5355", "\u7fa4\u804a", "\u534f\u4f5c", "enterprise", "\u4f01\u4e1a\u7248",
            "slack", "\u98de\u4e66", "\u9489\u9489", "\u5de5\u4f5c\u6d41",
            "\u667a\u80fd\u4f53", "\u6d88\u606f", "\u901a\u77e5", "\u7ba1\u7406",
            "skywork", "\u5929\u5de5", "\u7528\u91cf\u5206\u6790", "\u652f\u51fa\u7ba1\u63a7",
            "harness", "\u4e3b\u52a8\u670d\u52a1", "\u4f4e\u529f\u8017",
        ],
    },
    {
        "id": "s2",
        "icon": "\U0001f50d",
        "title": "\u7248\u57572 \u00b7 \u72ec\u7acb\u7ad9SEO\u4e0eAI\u5185\u5bb9\u5de5\u5382",
        "nav_label": "SEO\u5185\u5bb9\u5de5\u5382",
        "keywords": [
            "seo", "geo", "cdn", "dom", "web", "ppt", "pencil",
            "\u5185\u5bb9", "\u6392\u7248", "\u7f16\u8f91", "\u72ec\u7acb\u7ad9",
            "\u524d\u7aef", "safari", "mcp", "\u7f51\u9875", "\u5f00\u53d1\u8005",
            "\u8c03\u8bd5", "\u6027\u80fd", "\u6f14\u793a", "\u5bfc\u5165",
        ],
    },
    {
        "id": "s3",
        "icon": "\U0001f3ac",
        "title": "\u7248\u57573 \u00b7 \u89c6\u9891AI\u751f\u6210\u4e0e\u6d77\u5916\u591a\u6e20\u9053\u5206\u53d1",
        "nav_label": "\u89c6\u9891AI\u5206\u53d1",
        "keywords": [
            "\u89c6\u9891", "video", "tiktok", "youtube", "\u526a\u8f91",
            "\u821e\u8e48", "\u5b9e\u65f6", "\u751f\u6210\u89c6\u9891", "\u5206\u53d1",
            "\u77ed\u89c6\u9891", "\u5e27", "ffmpeg", "\u8f6c\u5199", "\u5173\u952e\u5e27",
            "\u97f3\u9891", "skill", "\u7ad6\u5c4f", "\u5f00\u6e90",
        ],
    },
    {
        "id": "s4",
        "icon": "\U0001f4e2",
        "title": "\u7248\u57574 \u00b7 \u667a\u80fd\u5e7f\u544a\u6295\u6d41\u4e0e\u591a\u8bed\u8a00\u8425\u9500",
        "nav_label": "\u5e7f\u544a\u591a\u8bed\u8a00",
        "keywords": [
            "\u5e7f\u544a", "\u6295\u6d41", "\u591a\u8bed\u8a00", "\u8425\u9500",
            "\u5ba2\u670d", "\u6570\u5b57\u4eba", "\u964d\u672c",
            "\u5f00\u6e90", "\u4ee3\u7801", "\u8bed\u97f3", "\u5bf9\u8bdd",
            "\u5546\u52a1", "\u6295\u653e", "token", "pxpipe", "\u538b\u7f29",
            "copilot",
        ],
    },
    {
        "id": "s5",
        "icon": "\U0001f30d",
        "title": "\u7248\u57575 \u00b7 \u5168\u7403\u51fa\u6d77\u884c\u4e1a\u52a8\u6001\u4e0eAI\u8d8b\u52bf",
        "nav_label": "\u884c\u4e1a\u8d8b\u52bf",
        "keywords": [
            "\u4f30\u503c", "\u878d\u8d44", "\u4e0a\u5e02", "\u653f\u7b56", "\u5408\u89c4",
            "\u7f51\u4fe1\u529e", "\u88c1\u5458", "\u653f\u5e9c", "\u6301\u80a1",
            "\u884c\u4e1a", "\u8d8b\u52bf", "\u9650\u7528", "\u5fae\u8f6f",
            "meta", "openai", "google", "\u82b1\u65d7", "adobe", "frontier",
            "\u589e\u8d44", "\u6ce8\u8d44", "\u652f\u4ed8\u5b9d", "\u516c\u6d4b",
            "\u5f81\u6c42\u610f\u89c1", "\u7ba1\u7406\u529e\u6cd5", "\u89c4\u8303",
            "\u5de5\u7a0b\u5e08", "\u6210\u672c", "\u63a7\u5236\u6210\u672c",
        ],
    },
]

# ── Exclude keywords (bottom-layer tech noise) ──────────────────────────────
EXCLUDE_KEYWORDS = [
    # Academic / research
    "\u8bba\u6587", "paper", "research", "arxiv",
    "apple machine learning research",
    # Model training / fine-tuning
    "\u5fae\u8c03", "fine-tune", "fine tune", "finetune", "lora",
    "\u6a21\u578b\u6743\u91cd", "rlhf", "dpo", "alignment",
    "forgetrain", "\u9884\u8bad\u7ec3", "\u8bad\u7ec3\u6846\u67b6",
    # Benchmark / evaluation
    "\u57fa\u51c6", "benchmark", "\u6392\u884c\u699c", "leaderboard",
    # Inference optimization
    "\u63a8\u7406\u4f18\u5316", "\u91cf\u5316\u538b\u7f29", "quantization",
    "pruning", "distillation", "\u526a\u679d",
    # Pure architecture / theory
    "transformer architecture", "attention mechanism",
    "\u5e7b\u89c9", "hallucination",
    "videflextok", "\u89c6\u9891\u5206\u8bcd",
    # Security / military / not cross-border
    "\u52d2\u7d22", "ransomware", "\u7f51\u7edc\u5b89\u5168",
    "\u4e94\u89d2\u5927\u697c", "\u519b\u4e8b\u7528\u9014",
    "\u8d85\u5bfc", "\u6750\u6599\u53d1\u73b0",
    "\u7528\u7535\u91cf", "\u95f2\u7f6e\u63a8\u7406", "gpu\u56de\u6536",
    "fitbit", "ghealth",
    "rube goldberg", "sglang",
    "\u591a\u667a\u80fd\u4f53\u56e2\u961f",
    # Tesla / non-AI news
    "\u81f4\u547d\u8f66\u7978", "fsd",
]


# ── API helpers ─────────────────────────────────────────────────────────────
def fetch_json(url, timeout=15):
    """Fetch JSON from URL with error handling."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"  WARN: fetch failed {url}: {e}", file=sys.stderr)
        return None


def fetch_daily():
    """Fetch latest daily report. Returns list of items with sourceUrl."""
    data = fetch_json(f"{AIHOT_BASE}/api/public/daily")
    if not data or not data.get("sections"):
        return [], None

    date_str = data.get("date", "")
    items = []
    for section in data["sections"]:
        for item in section.get("items", []):
            items.append(item)
    return items, date_str


def fetch_selected(since_iso, take=100):
    """Fetch selected items from past 24h. Items may lack sourceUrl."""
    url = f"{AIHOT_BASE}/api/public/items?mode=selected&since={since_iso}&take={take}"
    data = fetch_json(url)
    if not data:
        return []
    return data.get("items", [])


def get_permalink(item):
    """Get or construct permalink for an item."""
    permalink = item.get("permalink", "")
    if permalink:
        return permalink
    item_id = item.get("id", "")
    if item_id:
        return f"{AIHOT_BASE}/items/{item_id}"
    return AIHOT_BASE


def get_source_url(item):
    """Get source URL, falling back to permalink."""
    url = item.get("sourceUrl", "")
    if url and url.startswith("http"):
        return url
    return get_permalink(item)


# ── Filtering & categorization ──────────────────────────────────────────────
def is_tech_noise(text):
    """Check if item text matches bottom-layer tech noise keywords."""
    text_lower = text.lower()
    for kw in EXCLUDE_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    return False


def score_section(text, keywords):
    """Score how well text matches a section's keywords."""
    text_lower = text.lower()
    score = 0
    for kw in keywords:
        if kw.lower() in text_lower:
            score += 1
    return score


def categorize_item(item):
    """Return section id with highest score, or None if no match."""
    title = item.get("title", "")
    summary = item.get("summary", "")
    text = f"{title} {summary}"

    if is_tech_noise(text):
        return None

    best_section = None
    best_score = 0
    for section in SECTIONS:
        score = score_section(text, section["keywords"])
        if score > best_score:
            best_score = score
            best_section = section["id"]

    return best_section if best_score > 0 else None


def filter_and_categorize(all_items):
    """Filter items and categorize into sections. Returns {section_id: [items]}."""
    result = {s["id"]: [] for s in SECTIONS}
    seen_ids = set()
    seen_titles = set()

    for item in all_items:
        item_id = item.get("id", "")
        title = item.get("title", "")

        # Dedup by both id and title (daily API items lack id field)
        if item_id and item_id in seen_ids:
            continue
        if title and title in seen_titles:
            continue
        if item_id:
            seen_ids.add(item_id)
        if title:
            seen_titles.add(title)

        section_id = categorize_item(item)
        if section_id and len(result[section_id]) < MAX_PER_SECTION:
            result[section_id].append(item)

    return result


# ── Time formatting ─────────────────────────────────────────────────────────
def format_time(iso_str):
    """Convert ISO timestamp to Beijing time colloquial format."""
    if not iso_str:
        return "\u672a\u77e5\u65f6\u95f4"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        beijing = dt.astimezone(BEIJING_TZ)
        now = datetime.now(BEIJING_TZ)

        if beijing.date() == now.date():
            return f"\u4eca\u5929 {beijing.strftime('%H:%M')}"
        elif beijing.date() == (now - timedelta(days=1)).date():
            return f"\u6628\u5929 {beijing.strftime('%H:%M')}"
        elif beijing.date() == (now - timedelta(days=2)).date():
            return "\u524d\u5929"
        else:
            return f"{beijing.month}\u6708{beijing.day}\u65e5"
    except (ValueError, TypeError):
        return "\u672a\u77e5\u65f6\u95f4"


# ── Summary truncation ──────────────────────────────────────────────────────
def truncate_summary(summary):
    """Truncate summary to ~60 chars, cutting at sentence boundary."""
    if not summary:
        return ""
    summary = summary.strip()
    if len(summary) <= SUMMARY_MAX_CHARS:
        return summary

    # Try to cut at a sentence boundary
    cut = summary[:SUMMARY_MAX_CHARS]
    # Find last period/comma in Chinese or English
    for delim in ["\u3002", "\uff0c", ".", ",", "\u3001", "\uff1b", ";"]:
        pos = cut.rfind(delim)
        if pos > SUMMARY_MAX_CHARS // 2:
            return cut[:pos] + "\u2026"
    return cut + "\u2026"


# ── Source name extraction ──────────────────────────────────────────────────
def get_source_name(item):
    """Extract readable source name."""
    name = item.get("sourceName", "")
    if name:
        return name
    # Try to extract domain from sourceUrl
    url = item.get("sourceUrl", "")
    if url:
        m = re.match(r"https?://(?:www\.)?([^/]+)", url)
        if m:
            return m.group(1)
    return "AI HOT"


# ── HTML generation ─────────────────────────────────────────────────────────
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI HOT \u8de8\u5883\u51fa\u6d77\u4e13\u80fd\u7248 \u2014 {date_display}\u6668\u62a5</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
:root{{
  --bg:#070b14;--bg2:#0d1220;--card:#111827;--card-hover:#16203a;
  --border:#1e293b;--text:#e2e8f0;--text2:#94a3b8;--text3:#64748b;
  --cyan:#06b6d4;--indigo:#6366f1;--amber:#f59e0b;--emerald:#10b981;
  --rose:#f43f5e;--violet:#8b5cf6;--sky:#0ea5e9;
}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;line-height:1.6;overflow-x:hidden}}
a{{color:inherit;text-decoration:none}}
.hero{{position:relative;padding:48px 24px 40px;text-align:center;overflow:hidden;
  background:linear-gradient(135deg,#0a0e1a 0%,#0f172a 50%,#0a0e1a 100%);
  border-bottom:1px solid var(--border)}}
.hero::before{{content:'';position:absolute;top:-50%;left:-10%;width:120%;height:200%;
  background:radial-gradient(ellipse at 30% 40%,rgba(99,102,241,.08) 0%,transparent 50%),
             radial-gradient(ellipse at 70% 60%,rgba(6,182,212,.06) 0%,transparent 50%);
  pointer-events:none}}
.hero-inner{{position:relative;max-width:1100px;margin:0 auto}}
.hero-badge{{display:inline-flex;align-items:center;gap:6px;padding:5px 14px;border-radius:20px;
  background:rgba(6,182,212,.1);border:1px solid rgba(6,182,212,.25);color:var(--cyan);
  font-size:12px;font-weight:600;letter-spacing:1px;margin-bottom:16px}}
.hero-badge .dot{{width:7px;height:7px;border-radius:50%;background:var(--cyan);animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.3}}}}
.hero h1{{font-size:28px;font-weight:800;letter-spacing:-.5px;margin-bottom:6px;
  background:linear-gradient(90deg,#e2e8f0,#94a3b8);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.hero-date{{font-size:15px;color:var(--text2);margin-bottom:28px}}
.hero-stats{{display:flex;flex-wrap:wrap;gap:12px;justify-content:center}}
.stat-chip{{display:flex;flex-direction:column;align-items:center;gap:2px;padding:12px 20px;border-radius:12px;
  background:var(--card);border:1px solid var(--border);min-width:100px;transition:.2s}}
.stat-chip:hover{{border-color:var(--card-hover);transform:translateY(-2px)}}
.stat-chip .num{{font-size:24px;font-weight:800;color:var(--cyan)}}
.stat-chip .label{{font-size:11px;color:var(--text3);letter-spacing:.5px}}
.stat-chip.s1 .num{{color:var(--cyan)}}
.stat-chip.s2 .num{{color:var(--indigo)}}
.stat-chip.s3 .num{{color:var(--amber)}}
.stat-chip.s4 .num{{color:var(--emerald)}}
.stat-chip.s5 .num{{color:var(--violet)}}
.stat-chip.total .num{{color:var(--rose)}}
.nav{{position:sticky;top:0;z-index:100;background:rgba(7,11,20,.92);backdrop-filter:blur(12px);
  border-bottom:1px solid var(--border);padding:10px 0}}
.nav-inner{{max-width:1100px;margin:0 auto;display:flex;gap:8px;justify-content:center;flex-wrap:wrap;padding:0 16px}}
.nav a{{padding:6px 16px;border-radius:8px;font-size:13px;font-weight:500;color:var(--text2);
  border:1px solid transparent;transition:.2s;white-space:nowrap}}
.nav a:hover{{color:var(--text);border-color:var(--border);background:var(--card)}}
.nav a .nav-emoji{{margin-right:4px}}
.container{{max-width:1100px;margin:0 auto;padding:0 16px}}
.section{{padding:36px 0 8px}}
.section-header{{display:flex;align-items:center;gap:10px;margin-bottom:20px;padding-bottom:10px;
  border-bottom:1px solid var(--border)}}
.section-icon{{width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;
  font-size:16px;flex-shrink:0}}
.section-header h2{{font-size:17px;font-weight:700;color:var(--text)}}
.section-header .count{{font-size:13px;color:var(--text3);margin-left:auto}}
.s1 .section-icon{{background:rgba(6,182,212,.12);border:1px solid rgba(6,182,212,.3)}}
.s2 .section-icon{{background:rgba(99,102,241,.12);border:1px solid rgba(99,102,241,.3)}}
.s3 .section-icon{{background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.3)}}
.s4 .section-icon{{background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.3)}}
.s5 .section-icon{{background:rgba(139,92,246,.12);border:1px solid rgba(139,92,246,.3)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:14px;padding-bottom:28px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px;
  transition:.2s;position:relative;overflow:hidden}}
.card::before{{content:'';position:absolute;top:0;left:0;width:3px;height:100%;transition:.2s;opacity:.6}}
.s1 .card::before{{background:var(--cyan)}}
.s2 .card::before{{background:var(--indigo)}}
.s3 .card::before{{background:var(--amber)}}
.s4 .card::before{{background:var(--emerald)}}
.s5 .card::before{{background:var(--violet)}}
.card:hover{{background:var(--card-hover);border-color:#2a3550;transform:translateY(-2px)}}
.card:hover::before{{opacity:1;width:4px}}
.card-top{{display:flex;align-items:center;gap:8px;margin-bottom:8px}}
.card-num{{font-size:13px;font-weight:800;color:var(--text3);min-width:22px}}
.card-source{{display:inline-block;font-size:11px;padding:2px 8px;border-radius:6px;
  background:rgba(148,163,184,.1);color:var(--text2);border:1px solid rgba(148,163,184,.15);
  max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.card-time{{font-size:11px;color:var(--text3);margin-left:auto;white-space:nowrap}}
.card h3{{font-size:14.5px;font-weight:600;line-height:1.45;margin-bottom:8px;color:var(--text)}}
.card p{{font-size:13px;color:var(--text2);line-height:1.55;margin-bottom:12px;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}}
.card-link{{display:inline-flex;align-items:center;gap:4px;font-size:12px;font-weight:500;
  color:var(--cyan);transition:.2s}}
.s2 .card-link{{color:var(--indigo)}}
.s3 .card-link{{color:var(--amber)}}
.s4 .card-link{{color:var(--emerald)}}
.s5 .card-link{{color:var(--violet)}}
.card-link:hover{{text-decoration:underline;gap:6px}}
.footer{{text-align:center;padding:32px 16px 40px;border-top:1px solid var(--border);margin-top:20px}}
.footer p{{font-size:12px;color:var(--text3);margin-bottom:4px}}
.footer .total-line{{font-size:14px;color:var(--text2);font-weight:600;margin-bottom:8px}}
.footer .source-line{{font-size:11px}}
@media(max-width:640px){{
  .hero h1{{font-size:22px}}
  .hero-stats{{gap:8px}}
  .stat-chip{{min-width:80px;padding:10px 14px}}
  .stat-chip .num{{font-size:20px}}
  .grid{{grid-template-columns:1fr}}
  .nav-inner{{justify-content:flex-start;overflow-x:auto;flex-wrap:nowrap;-webkit-overflow-scrolling:touch}}
  .nav a{{flex-shrink:0}}
}}
</style>
</head>
<body>

<!-- HERO -->
<div class="hero">
  <div class="hero-inner">
    <div class="hero-badge"><span class="dot"></span> AI HOT \u00b7 \u8de8\u5883\u51fa\u6d77\u4e13\u80fd\u7248</div>
    <h1>\u8de8\u5883\u51fa\u6d77 AI \u5e94\u7528\u6668\u62a5</h1>
    <div class="hero-date">{hero_date}</div>
    <div class="hero-stats">
      <div class="stat-chip total"><span class="num">{total}</span><span class="label">\u603b\u6761\u6570</span></div>
      {stat_chips}
    </div>
  </div>
</div>

<!-- NAV -->
<nav class="nav">
  <div class="nav-inner">
    {nav_links}
  </div>
</nav>

<div class="container">
{sections_html}
</div>

<!-- FOOTER -->
<div class="footer">
  <p class="total-line">\u5171 {total} \u6761 \u00b7 5 \u4e2a\u7248\u5757</p>
  <p class="source-line">\u6570\u636e\u6765\u6e90\uff1aAI HOT (aihot.virxact.com) \u00b7 \u65e5\u62a5\u65e5\u671f\uff1a{daily_date} \u00b7 \u8fc7\u6ee4\u6807\u51c6\uff1a\u8de8\u5883\u51fa\u6d77 / \u5916\u8d38B2B / \u72ec\u7acb\u7ad9 / \u6d77\u5916\u8425\u9500\u5f3a\u76f8\u5173</p>
  <p class="source-line">\u751f\u6210\u65f6\u95f4\uff1a{gen_time} \u5317\u4eac\u65f6\u95f4 \u00b7 Powered by GitHub Actions</p>
</div>

<script>
document.querySelectorAll('.nav a').forEach(link=>{{
  link.addEventListener('click',e=>{{
    e.preventDefault();
    const target=document.querySelector(link.getAttribute('href'));
    if(target){{
      const offset=target.offsetTop-60;
      window.scrollTo({{top:offset,behavior:'smooth'}});
    }}
  }});
}});
const sections=document.querySelectorAll('.section');
const navLinks=document.querySelectorAll('.nav a');
window.addEventListener('scroll',()=>{{
  let current='';
  sections.forEach(sec=>{{
    if(window.scrollY>=sec.offsetTop-80) current=sec.id;
  }});
  navLinks.forEach(link=>{{
    link.style.color='';
    link.style.borderColor='';
    link.style.background='';
    if(link.getAttribute('href')==='#'+current){{
      link.style.color='var(--text)';
      link.style.borderColor='var(--border)';
      link.style.background='var(--card)';
    }}
  }});
}});
</script>
</body>
</html>"""


def generate_html(categorized, daily_date_str):
    """Generate full HTML from categorized items."""
    now_beijing = datetime.now(BEIJING_TZ)
    date_display = f"{now_beijing.year}\u5e74{now_beijing.month}\u6708{now_beijing.day}\u65e5"
    gen_time = now_beijing.strftime("%-m\u6708%-d\u65e5 %H:%M")

    if daily_date_str:
        daily_date_display = daily_date_str
    else:
        daily_date_display = "\u672a\u77e5"

    hero_date = f"\u6570\u636e\u65e5\u671f\uff1a{daily_date_display}\uff08\u65e5\u62a5\uff09 \u00b7 \u751f\u6210\u65f6\u95f4\uff1a{gen_time} \u5317\u4eac\u65f6\u95f4"

    # Stats
    total = sum(len(items) for items in categorized.values())
    stat_chips = ""
    for s in SECTIONS:
        count = len(categorized[s["id"]])
        stat_chips += (
            f'<div class="stat-chip {s["id"]}">'
            f'<span class="num">{count}</span>'
            f'<span class="label">{s["nav_label"]}</span>'
            f'</div>\n'
        )

    # Nav links
    nav_links = ""
    for s in SECTIONS:
        nav_links += (
            f'<a href="#{s["id"]}">'
            f'<span class="nav-emoji">{s["icon"]}</span>{s["nav_label"]}'
            f'</a>\n'
        )

    # Sections HTML
    sections_html = ""
    global_num = 0
    for s in SECTIONS:
        items = categorized[s["id"]]
        if not items:
            continue
        count = len(items)
        section_html = f"""
<section class="section {s['id']}" id="{s['id']}">
  <div class="section-header">
    <div class="section-icon">{s['icon']}</div>
    <h2>{html_escape(s['title'])}</h2>
    <span class="count">{count} \u6761</span>
  </div>
  <div class="grid">
"""
        for item in items:
            global_num += 1
            num_str = f"{global_num:02d}"
            title = html_escape(item.get("title", ""))
            summary = html_escape(truncate_summary(item.get("summary", "")))
            source = html_escape(get_source_name(item))
            time_str = format_time(item.get("publishedAt", ""))
            url = html_escape(get_source_url(item))

            section_html += f"""    <div class="card">
      <div class="card-top">
        <span class="card-num">{num_str}</span>
        <span class="card-source">{source}</span>
        <span class="card-time">{time_str}</span>
      </div>
      <h3>{title}</h3>
      <p>{summary}</p>
      <a href="{url}" target="_blank" rel="noopener noreferrer" class="card-link">\u9605\u8bfb\u539f\u6587 \u2192</a>
    </div>
"""
        section_html += "  </div>\n</section>\n"
        sections_html += section_html

    return HTML_TEMPLATE.format(
        date_display=date_display,
        hero_date=hero_date,
        total=total,
        stat_chips=stat_chips,
        nav_links=nav_links,
        sections_html=sections_html,
        daily_date=daily_date_display,
        gen_time=gen_time,
    )


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("AI HOT \u8de8\u5883\u51fa\u6d77\u4e13\u80fd\u7248 \u2014 \u81ea\u52a8\u751f\u6210")
    print("=" * 60)

    # 1. Fetch daily report
    print("\n[1/4] Fetching daily report...")
    daily_items, daily_date = fetch_daily()
    print(f"  Daily items: {len(daily_items)}, date: {daily_date}")

    # 2. Fetch selected items from past 24h
    print("\n[2/4] Fetching selected items (past 24h)...")
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    selected_items = fetch_selected(since)
    print(f"  Selected items: {len(selected_items)}")

    # 3. Merge, filter, categorize
    print("\n[3/4] Filtering & categorizing...")
    all_items = daily_items + selected_items
    categorized = filter_and_categorize(all_items)
    total = sum(len(items) for items in categorized.values())
    for s in SECTIONS:
        print(f"  {s['id']}: {len(categorized[s['id']])} items")
    print(f"  TOTAL: {total} items (from {len(all_items)} raw)")

    if total == 0:
        print("\n  WARN: No items passed filter. Generating empty page.", file=sys.stderr)

    # 4. Generate HTML
    print("\n[4/4] Generating HTML...")
    html = generate_html(categorized, daily_date)

    output_path = os.environ.get("OUTPUT_PATH", "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Written to: {output_path} ({len(html)} bytes)")

    print("\nDone!")


if __name__ == "__main__":
    main()
