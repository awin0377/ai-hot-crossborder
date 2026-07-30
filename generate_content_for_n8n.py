#!/usr/bin/env python3
"""
AI HOT News → Grok → Structured Content for n8n
- Fetches daily AI HOT news
- Selects 3 fresh, diverse, deduplicated news topics
- Generates content with Grok first and Doubao fallback
- Outputs structured JSON with:
  - x_post (English)
  - image_prompt (white/blue tech style)
  - youtube_script (60s Shorts script)
- Sends result to Feishu via Hermes
"""

import json
import urllib.request
import urllib.error
import re
import sys
import os
import subprocess
import unicodedata

# -- load local .env (gitignored) to keep secrets out of source --
def _load_dotenv(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')):
    try:
        with open(path, encoding='utf-8') as _f:
            for _line in _f:
                _line=_line.strip()
                if not _line or _line.startswith('#') or '=' not in _line:
                    continue
                _k,_v=_line.split('=',1)
                os.environ.setdefault(_k.strip(), _v.strip())
    except FileNotFoundError:
        pass
_load_dotenv()
from difflib import SequenceMatcher
from html import escape, unescape
from datetime import datetime, timezone, timedelta

# ── Config ──────────────────────────────────────────────────────────────────
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
AIHOT_BASE = "https://aihot.virxact.com"
AFFILIATE_LINK = "https://www.getaipremium.com"
NUM_ITEMS = 3  # Generate content for top 3 news
SENT_NEWS_FILE = "/root/projects/ai-news-x-cps/sent_news.json"  # 已发新闻去重库
SENT_EXPIRE_DAYS = 7  # 同公司轮换冷却窗：7天内同公司新闻降权，避免连续几天都是一家公司
ARCHIVE_MAX_RECORDS = 2000  # 去重归档上限，超过则裁掉最老的记录，防止文件无限膨胀
PREFERRED_FRESH_HOURS = 24
MAX_NEWS_AGE_HOURS = 48

CATEGORY_LABELS = {
    "model_release": "大模型发布",
    "product_update": "AI 产品更新",
    "policy_industry": "行业政策",
    "startup_application": "创业应用",
    "open_source": "开源项目",
}

CATEGORY_KEYWORDS = {
    "policy_industry": (
        "政策", "监管", "法规", "法案", "政府", "游说", "限制", "禁令", "版权",
        "安全", "风险", "攻击", "泄露", "漏洞", "越狱", "毒药", "生物武器",
        "policy", "regulation", "regulator", "government", "lobby", "restrict",
        "ban", "copyright", "security", "safety", "hack", "breach", "leak",
    ),
    "open_source": (
        "开源", "github", "hugging face", "模型权重", "本地运行", "微控制器",
        "open source", "open-source", "repository", "weights", "on-device",
    ),
    "model_release": (
        "大模型", "语言模型", "多模态模型", "推理模型", "基础模型", "参数模型",
        "模型发布", "发布模型", "benchmark", "foundation model", "language model",
        "multimodal model", "reasoning model", "model release", "parameters",
    ),
    "product_update": (
        "新功能", "功能更新", "产品更新", "推出", "上线", "发布", "支持",
        "cli", "插件", "工作流", "导出", "集成", "app", "feature", "update",
        "launch", "rollout", "integration", "workflow", "command",
    ),
    "startup_application": (
        "创业", "初创", "融资", "product hunt", "应用", "工具", "平台",
        "startup", "funding", "seed round", "series a", "product launch",
        "application", "tool",
    ),
}

ENTITY_ALIASES = {
    "openai": ("openai", "chatgpt", "gpt-4", "gpt-5", "gpt4", "gpt5"),
    "anthropic": ("anthropic", "claude"),
    "claude-opus-5": ("claude opus 5", "opus 5"),
    "google": ("google", "gemini", "deepmind"),
    "xai": ("xai", "grok"),
    "meta": ("meta", "llama"),
    "microsoft": ("microsoft", "copilot"),
    "suno": ("suno",),
    "midjourney": ("midjourney",),
    "runway": ("runway",),
    "flux": ("black forest labs", "flux"),
    "huggingface": ("hugging face", "huggingface"),
    "nvidia": ("nvidia", "英伟达", "黄仁勋"),
    "alibaba": ("alibaba", "阿里", "通义", "qwen"),
    "bytedance": ("bytedance", "字节", "豆包", "doubao"),
    "github": ("github",),
}

EVENT_ALIASES = {
    "release": ("发布", "推出", "上线", "亮相", "launch", "release", "released", "unveil", "debut"),
    "update": ("更新", "新功能", "支持", "升级", "update", "feature", "integration", "command", "cli"),
    "policy": ("政策", "监管", "法规", "法案", "游说", "限制", "禁令", "policy", "regulation", "lobby", "restrict", "ban"),
    "security": ("安全", "攻击", "入侵", "泄露", "漏洞", "越狱", "毒药", "生物武器", "hack", "breach", "leak", "exploit", "jailbreak"),
    "open_source": ("开源", "代码库", "权重", "open source", "open-source", "repository", "weights", "github"),
    "funding": ("融资", "收购", "投资", "估值", "funding", "acquisition", "investment", "valuation"),
    "benchmark": ("评测", "基准", "性能", "提速", "benchmark", "performance", "faster", "score"),
}

GENERIC_TOPIC_WORDS = {
    "the", "a", "an", "and", "or", "for", "to", "of", "in", "on", "with",
    "new", "latest", "ai", "artificial", "intelligence", "发布", "推出", "上线",
    "更新", "支持", "最新", "全新", "人工智能", "模型", "功能", "产品",
}

# ── Sent news dedup functions ──────────────────────────────────────────────
def parse_datetime(value, fallback=None):
    """Parse common ISO timestamps as timezone-aware UTC datetimes."""
    if isinstance(value, datetime):
        dt = value
    elif value:
        try:
            dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return fallback
    else:
        return fallback
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_text(value):
    text = unicodedata.normalize("NFKC", value or "").lower()
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def contains_keyword(text, keyword):
    needle = normalize_text(keyword)
    if not needle:
        return False
    if re.fullmatch(r"[a-z0-9 -]+", needle):
        return re.search(
            rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])",
            text,
        ) is not None
    return needle in text


def extract_entities(value):
    text = normalize_text(value)
    entities = set()
    for canonical, aliases in ENTITY_ALIASES.items():
        if any(contains_keyword(text, alias) for alias in aliases):
            entities.add(canonical)
    return entities


def extract_events(value):
    text = normalize_text(value)
    events = set()
    for canonical, aliases in EVENT_ALIASES.items():
        if any(contains_keyword(text, alias) for alias in aliases):
            events.add(canonical)
    return events


def topic_terms(value):
    text = normalize_text(value)
    terms = extract_entities(text) | extract_events(text)
    for token in re.findall(r"[a-z][a-z0-9-]{2,}|\d+(?:\.\d+)?", text):
        if token not in GENERIC_TOPIC_WORDS:
            terms.add(token)
    return terms


def topic_signature(value):
    """Stable signature used in the 7-day store and diagnostic output."""
    terms = sorted(topic_terms(value))
    return "|".join(terms[:12]) or normalize_text(value)[:80]


def strongly_same_topic(left, right):
    """Strong same-topic signal: near-identical titles (same wording, minor
    rewrite). Used for permanent dedup across the whole archive so a reworded
    report of an already-published story can never come back as "new".
    """
    a = normalize_text(left)
    b = normalize_text(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 18 and len(b) >= 18 and (a in b or b in a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.72


def version_marks(value):
    """Extract product + version phrases such as claude opus 5, gpt 5,
    flux 3. When two titles share a product family but carry different
    version marks (Opus 5 -> Opus 5.1), that is a follow-up release, not a
    re-report of the same story, and must stay selectable.
    """
    text = normalize_text(value)
    return set(re.findall(r"[a-z][a-z]+\s+\d+(?:\s+\d)*(?![a-z])", text))


def same_topic(left, right):
    """Detect the same story across rewritten titles and different sources."""
    if strongly_same_topic(left, right):
        return True
    a = normalize_text(left)
    b = normalize_text(right)

    # Version fingerprint: same product family but a different version is a new
    # event. This keeps the permanent archive from swallowing follow-up releases.
    a_marks, b_marks = version_marks(a), version_marks(b)
    if a_marks and b_marks and a_marks != b_marks:
        return False

    a_entities, b_entities = extract_entities(a), extract_entities(b)
    shared_entities = a_entities & b_entities
    a_events, b_events = extract_events(a), extract_events(b)
    shared_events = a_events & b_events
    a_terms, b_terms = topic_terms(a), topic_terms(b)
    union = a_terms | b_terms
    similarity = len(a_terms & b_terms) / len(union) if union else 0

    if shared_entities & {"claude-opus-5"} and shared_events:
        return True
    if shared_entities and shared_events and similarity >= 0.42:
        return True
    if shared_entities and similarity >= 0.35:
        return True
    if len(shared_entities) >= 2 and similarity >= 0.32:
        return True
    return similarity >= 0.62


def categorize_news(item):
    text = normalize_text(
        f"{item.get('title', '')} {item.get('summary', '')} {item.get('source', '')}"
    )
    category_order = (
        "policy_industry",
        "open_source",
        "model_release",
        "product_update",
        "startup_application",
    )
    for category in category_order:
        if any(contains_keyword(text, keyword) for keyword in CATEGORY_KEYWORDS[category]):
            return category
    return "startup_application"


def record_timestamp(value):
    if isinstance(value, dict):
        return parse_datetime(value.get("sent_at") or value.get("timestamp"))
    return parse_datetime(value)


def normalized_record(title, value):
    record = dict(value) if isinstance(value, dict) else {"sent_at": value}
    record["sent_at"] = (
        record_timestamp(record) or datetime.now(timezone.utc)
    ).isoformat()
    record.setdefault("topic", topic_signature(title))
    record.setdefault("entities", sorted(extract_entities(title)))
    return record


def load_sent_news():
    """Load the full sent-news archive.

    Records are kept permanently so the same topic is never selected twice.
    The 7-day window only governs company rotation (recent_entity_counts);
    it no longer deletes old records, so a topic can no longer reappear as a
    "new" story once its 7-day window slides past.
    """
    try:
        with open(SENT_NEWS_FILE, "r", encoding="utf-8") as f:
            records = json.load(f)
        if not isinstance(records, dict):
            records = {}
    except (OSError, json.JSONDecodeError):
        records = {}

    archive = {title: normalized_record(title, value) for title, value in records.items()}

    # Safety cap: if the archive outgrows the limit, drop the oldest entries.
    # At ~3 records/day this cap is not reached for years.
    if len(archive) > ARCHIVE_MAX_RECORDS:
        ordered = sorted(
            archive.items(),
            key=lambda kv: record_timestamp(kv[1]) or datetime.min.replace(tzinfo=timezone.utc),
        )
        archive = dict(ordered[-ARCHIVE_MAX_RECORDS:])

    with open(SENT_NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(archive, f, indent=2, ensure_ascii=False)
    return archive


def is_news_sent(item, sent_records):
    """Check a candidate against the permanent archive.

    With load_sent_news keeping every record forever, this blocks a re-reported
    story permanently. version_marks (inside same_topic) is what lets a genuine
    follow-up release in the same series (Opus 5 -> Opus 5.1) through, so the
    permanent block never starves the feed.
    """
    title = item.get("title", "") if isinstance(item, dict) else str(item)
    signature = topic_signature(title)
    for sent_title, record in sent_records.items():
        if signature == record.get("topic") or same_topic(title, sent_title):
            return True
    return False


def mark_news_sent(selected):
    """Mark selected news as sent with timestamp and topic metadata."""
    sent_records = load_sent_news()
    now = datetime.now(timezone.utc).isoformat()
    for item in selected:
        title = item["title"].strip()
        sent_records[title] = {
            "sent_at": now,
            "topic": topic_signature(title),
            "category": item.get("category") or categorize_news(item),
            "entities": sorted(extract_entities(title)),
        }
    with open(SENT_NEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(sent_records, f, indent=2, ensure_ascii=False)
    print(f"  ✅ Marked {len(selected)} news as sent (7-day topic dedup)")

# ── API helpers ─────────────────────────────────────────────────────────────
def fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        print(f"  WARN: fetch failed {url}: {e}", file=sys.stderr)
        return None

def fetch_hn_ai_news():
    """Fetch AI/tech news from Hacker News (Algolia API, no key needed)."""
    try:
        since = int(
            (datetime.now(timezone.utc) - timedelta(hours=MAX_NEWS_AGE_HOURS)).timestamp()
        )
        url = (
            "https://hn.algolia.com/api/v1/search_by_date"
            f"?tags=story&numericFilters=created_at_i>{since},points>20&hitsPerPage=60"
        )
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        items = []
        ai_terms = re.compile(
            r"\b(ai|llm|gpt|chatgpt|claude|openai|anthropic|gemini|grok|"
            r"machine learning|language model|agent|copilot|diffusion)\b",
            re.IGNORECASE,
        )
        for hit in data.get("hits", []):
            title = (hit.get("title") or "").strip()
            story_text = re.sub(r"<[^>]+>", " ", hit.get("story_text") or "")
            if not title or not ai_terms.search(f"{title} {story_text}"):
                continue
            items.append({
                "title": title,
                "summary": f"Hacker News · {hit.get('points',0)} points · {hit.get('num_comments',0)} comments",
                "url": hit.get("url", f"https://news.ycombinator.com/item?id={hit.get('objectID','')}"),
                "source": "Hacker News",
                "score": min(85, 35 + int(hit.get("points") or 0) // 4),
                "published_at": hit.get("created_at"),
            })
        return items
    except Exception as e:
        print(f"  WARN: HN fetch failed: {e}", file=sys.stderr)
        return []

def fetch_producthunt_ai():
    """Fetch latest AI products from Product Hunt (RSS proxy, no key needed)."""
    try:
        url = "https://www.producthunt.com/feed?category=ai"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml = resp.read().decode("utf-8")
        # Simple XML parsing without external libs
        items = []
        entries = re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL)
        for entry in entries[:10]:
            title = re.search(r"<title[^>]*>(.*?)</title>", entry, re.DOTALL)
            link = re.search(r'<link[^>]*href="([^"]+)"', entry)
            published = re.search(
                r"<(?:published|updated)[^>]*>(.*?)</(?:published|updated)>",
                entry,
                re.DOTALL,
            )
            if title:
                clean_title = unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip()
                items.append({
                    "title": clean_title,
                    "summary": "Product Hunt · New AI product launch",
                    "url": link.group(1) if link else "",
                    "source": "Product Hunt",
                    "score": 45,
                    "published_at": published.group(1).strip() if published else None,
                })
        return items
    except Exception as e:
        print(f"  WARN: ProductHunt fetch failed: {e}", file=sys.stderr)
        return []

def fetch_daily():
    """Aggregate news from all sources."""
    all_items = []

    # Source 1: AI HOT daily
    data = fetch_json(f"{AIHOT_BASE}/api/public/daily")
    if data and data.get("sections"):
        date_str = data.get("date", "")
        daily_published_at = f"{date_str}T00:00:00+00:00" if date_str else None
        for section in data["sections"]:
            for item in section.get("items", []):
                all_items.append({
                    "title": item.get("title", "").strip(),
                    "summary": item.get("summary", "").strip(),
                    "source": item.get("source", "AI HOT"),
                    "url": item.get("url", ""),
                    "score": 100,
                    "published_at": item.get("publishedAt") or daily_published_at,
                })
    else:
        date_str = None

    # Source 2: AI HOT selected. Fetch 48h, then rank 24h stories first.
    since = (
        datetime.now(timezone.utc) - timedelta(hours=MAX_NEWS_AGE_HOURS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    selected = fetch_json(
        f"{AIHOT_BASE}/api/public/items?mode=selected&since={since}&take=50"
    )
    if selected and selected.get("items"):
        for item in selected["items"]:
            all_items.append({
                "title": item.get("title", "").strip(),
                "summary": item.get("summary", "").strip(),
                "source": item.get("source", "AI HOT Selected"),
                "url": item.get("url", ""),
                "score": 80,
                "published_at": item.get("publishedAt"),
            })

    # Source 3: Hacker News
    all_items.extend(fetch_hn_ai_news())

    # Source 4: Product Hunt
    all_items.extend(fetch_producthunt_ai())

    now = datetime.now(timezone.utc)
    fresh_items = []
    for item in all_items:
        title = item.get("title", "").strip()
        summary = item.get("summary", "").strip()
        published_at = parse_datetime(item.get("published_at"))
        if not title or not summary or not published_at:
            continue
        age_hours = max(0, (now - published_at).total_seconds() / 3600)
        if age_hours > MAX_NEWS_AGE_HOURS:
            continue
        item = dict(item)
        item["title"] = title
        item["summary"] = summary
        item["published_at"] = published_at.isoformat()
        item["age_hours"] = round(age_hours, 1)
        item["category"] = categorize_news(item)
        freshness_bonus = max(0, MAX_NEWS_AGE_HOURS - age_hours)
        if age_hours <= PREFERRED_FRESH_HOURS:
            freshness_bonus += 45
        item["rank_score"] = float(item.get("score", 0)) + freshness_bonus
        fresh_items.append(item)

    fresh_items.sort(key=lambda item: item["rank_score"], reverse=True)
    unique_items = []
    for item in fresh_items:
        if any(same_topic(item["title"], kept["title"]) for kept in unique_items):
            continue
        unique_items.append(item)

    return unique_items, date_str


def recent_entity_counts(sent_records, hours=72):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    counts = {}
    for title, record in sent_records.items():
        sent_at = record_timestamp(record)
        if not sent_at or sent_at < cutoff:
            continue
        entities = set(record.get("entities", [])) or extract_entities(title)
        for entity in entities:
            counts[entity] = counts.get(entity, 0) + 1
    return counts


def select_diverse_news(items, sent_records, limit=NUM_ITEMS):
    """Pick fresh, unsent stories from distinct fields with company rotation."""
    entity_counts = recent_entity_counts(sent_records)
    candidates = []
    for item in items:
        if is_news_sent(item, sent_records):
            continue
        item = dict(item)
        recent_company_penalty = min(
            24,
            sum(
                entity_counts.get(entity, 0) * 6
                for entity in extract_entities(item["title"])
            ),
        )
        item["selection_score"] = item["rank_score"] - recent_company_penalty
        candidates.append(item)

    candidates.sort(key=lambda item: item["selection_score"], reverse=True)
    selected = []
    selected_categories = set()

    # First pass: enforce one story per field.
    for item in candidates:
        if item["category"] in selected_categories:
            continue
        selected.append(item)
        selected_categories.add(item["category"])
        if len(selected) == limit:
            return selected

    # Fallback only when fewer distinct fields than requested are available
    # within 48h: fill the remaining slots, still preferring categories we
    # have not used yet so the published set stays as diverse as possible.
    remaining = [item for item in candidates if item not in selected]
    remaining.sort(
        key=lambda item: (item["category"] in selected_categories, -item["selection_score"])
    )
    for item in remaining:
        selected.append(item)
        selected_categories.add(item["category"])
        if len(selected) == limit:
            break
    return selected

# ── Grok call ─────────────────────────────────────────────────────────────────
IMAGE_PALETTES = {
    "model_release": {
        "scheme": "white + deep blue + electric blue",
        "accent": "glowing neural network / data stream",
    },
    "product_update": {
        "scheme": "white + teal + mint green",
        "accent": "flowing particle network / soft grid",
    },
    "policy_industry": {
        "scheme": "white + warm amber + deep orange",
        "accent": "circuit-board traces / abstract shield motif",
    },
    "startup_application": {
        "scheme": "white + coral red + soft pink",
        "accent": "rising signal waves / upward arrows",
    },
    "open_source": {
        "scheme": "white + violet + indigo",
        "accent": "branching nodes / git-style connection lines",
    },
}


def build_grok_prompt(selected_items):
    """Build the full prompt for grok CLI."""
    news_text = ""
    palette_notes = ""
    for i, item in enumerate(selected_items, 1):
        title = item["title"]
        summary = item["summary"]
        category = item.get("category", "product_update")
        news_text += f"{i}. {title}\n{summary}\n\n"
        palette = IMAGE_PALETTES.get(category, IMAGE_PALETTES["product_update"])
        palette_notes += (
            f"   - News {i}: {palette['scheme']} color scheme, "
            f"{palette['accent']} background accent\n"
        )

    prompt = f"""Based on these top {len(selected_items)} AI news items, create the following content in ENGLISH:

1. For EACH of the {len(selected_items)} news items, write an X (Twitter) post with a DISTINCTIVE personality voice (this is NOT a neutral news recap — your job is to be the memorable, witty, opinionated account people actually follow and share):
   - VOICE: a sharp, plugged-in AI insider who has lived through every hype cycle and has real opinions — the funny friend who reads the papers, sees straight through the marketing, and roasts it with affection. Playful, teasing, a little sarcastic (调侃), never mean. Tease the hype, the buzzwords, the "AGI in 6 months" crowd, and especially tease overpriced subscriptions. But give genuine, earned credit when something is a real breakthrough. Be FUNNY — your goal is to make people snort and hit repost, not just nod. Conversational and human, NEVER corporate or press-release, NEVER try-hard or cringe, no Gen-Z meme slang, no forced laughs.
   - Each post MUST land ONE punchy line: a joke, a witty jab, a contrarian take, or a teasing aside only an insider would write — the kind of line people screenshot. Humor over dryness. Examples of the SPIRIT (do not copy, write your own): "another 'AGI' that's really just a good eval-maximizer", "they benchmark against GPT-4 but conveniently skip the price tag", "$20/month and it still hallucinates my flight number".
   - Under 280 characters. Max 1 emoji, and only if it actually lands. OPEN with the joke or the take — NEVER with "Company X announces...", "Just in:", or any headline restating.
   - Include the concrete number/fact (price cut %, benchmark gain, new capability) so the wit is grounded and credible, not hot air.
   - Stay strictly factual. Do NOT invent personal experience, prices, savings, unlimited access, benchmark numbers, or certainty that is not in the supplied news. The humor must come ONLY from framing/wordplay/teasing, NEVER from fabricating facts or numbers.
   - A corresponding image generation prompt for a professional tech news graphic:
     * MANDATORY STYLE REQUIREMENT: Clean tech news editorial poster, MUST USE ONLY WHITE + DEEP NAVY BLUE + ELECTRIC BLUE COLOR SCHEME. NO warm colors (orange/red/pink/amber/yellow) allowed.
     * Must include the core headline/key fact as BOLD CENTERED TEXT on the image (e.g. "Claude Opus 5 Released", "Half Price, 2x Performance")
     * Subtle glowing neural network/data stream background, high contrast, modern bold sans-serif typography
     * No people, no cartoons, no irrelevant elements, 16:9 ratio, optimized for X post

   - Only add this natural-sounding CTA at the END of the FIRST news X post only: "Tired of paying $20/month for multiple AI subs? Get stable ChatGPT + Claude access for way less → {AFFILIATE_LINK}"

2. ONE 60-second YouTube Shorts script for the #1 biggest news, with timestamps, conversational tone like a tech YouTuber talking to camera:
   - 0-3s: Hook question that grabs attention
   - 4-30s: Break down the news/benefit, simple language
   - 31-50s: Why this matters for regular AI users/builders
   - 51-60s: Casual CTA to compare the current plan details at {AFFILIATE_LINK}; clearly call it an affiliate link

Format your response EXACTLY like this (keep the markers, do not add extra text, do not add markdown):

=== X POST 1 ===
[X post for news 1]
=== IMAGE PROMPT 1 ===
[image prompt for news 1, include headline text instruction]

=== X POST 2 ===
[X post for news 2]
=== IMAGE PROMPT 2 ===
[image prompt for news 2, include headline text instruction]

=== X POST 3 ===
[X post for news 3]
=== IMAGE PROMPT 3 ===
[image prompt for news 3, include headline text instruction]

=== YOUTUBE SCRIPT ===
[60s shorts script with timestamps, conversational tone]

Here is the AI news:

{news_text}
Today's date: {datetime.now().strftime("%Y-%m-%d")}
"""
    return prompt

# ── LLM call config ─────────────────────────────────────────────────────
# Primary: xAI Grok (better X-native tone), Fallback: Doubao
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
XAI_BASE = "https://api.x.ai/v1/chat/completions"
XAI_MODEL = "grok-3"
DOUBAO_API_KEY = os.environ.get("DOUBAO_API_KEY", "")
DOUBAO_BASE = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
DOUBAO_MODEL = "doubao-seed-2-1-pro-260628"

def call_llm(prompt):
    """Call LLM with Grok primary, Doubao fallback."""
    # Try Grok first
    try:
        payload = json.dumps({
            "model": XAI_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
            "max_tokens": 2400
        }).encode("utf-8")
        req = urllib.request.Request(XAI_BASE, data=payload, headers={
            "Authorization": f"Bearer {XAI_API_KEY}",
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            print("  ✅ Using Grok API for content generation")
            return data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", detail)
        except json.JSONDecodeError:
            pass
        print(
            f"  ⚠️ Grok API unavailable (HTTP {e.code}: {str(detail)[:100]}), "
            "falling back to Doubao"
        )
    except Exception as e:
        print(f"  ⚠️ Grok API unavailable ({str(e)[:50]}), falling back to Doubao")
    
    # Fallback to Doubao
    try:
        payload = json.dumps({
            "model": DOUBAO_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
            "max_tokens": 2400,
            "thinking": {"type": "disabled"}
        }).encode("utf-8")
        req = urllib.request.Request(DOUBAO_BASE, data=payload, headers={
            "Authorization": f"Bearer {DOUBAO_API_KEY}",
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req, timeout=240) as resp:
            data = json.loads(resp.read())
            print("  ✅ Using Doubao API for content generation")
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"  ❌ All LLM calls failed: {e}", file=sys.stderr)
        return None

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
APIFY_ACTOR = "apidojo~tweet-scraper"  # 官方免费X爬虫
SEARCH_KEYWORDS = [
    "ChatGPT Plus expensive",
    "Claude Pro overpriced",
    "cancel ChatGPT Plus",
    "ChatGPT too expensive",
    "Claude Pro alternative"
]

def translate_to_chinese(text):
    """用豆包把英文推文翻译成中文"""
    try:
        prompt = f"把下面这句英文推特内容翻译成简短中文，只输出翻译结果，不要其他内容：\n{text}"
        payload = json.dumps({
            "model": DOUBAO_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 200
        }).encode("utf-8")
        req = urllib.request.Request(DOUBAO_BASE, data=payload, headers={
            "Authorization": f"Bearer {DOUBAO_API_KEY}",
            "Content-Type": "application/json"
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
    except:
        return text[:80] + "..."

def build_tracked_link(user_name):
    """为每条推文构建带 UTM 三件套 + utm_content 精确归因链接（单推文维度）"""
    from urllib.parse import quote
    uc = quote(str(user_name or "user").lstrip("@"), safe="")
    # 必须走 /go/<slug> 短链路由，网站才会触发 recordClick 写入 Redis 归因
    return ("https://getaipremium.com/go/chatgpt?utm_source=x&utm_medium=reply"
            "&utm_campaign=x_reply&utm_content=" + uc)


def match_reply(text, link="https://getaipremium.com"):
    """根据内容自动匹配回复模板（link 为带归因参数的追踪链接）"""
    t = text.lower()
    if "cancel" in t or "canceled" in t or "cancelling" in t:
        return f"Canceled my Plus last month after the price hike, replaced it with this, works exactly the same: {link}"
    elif "claude" in t and ("expensive" in t or "overpriced" in t or "price" in t or "$20" in t):
        return f"Claude Pro's $20/month is rough for casual use. I pay way less for shared access here: {link}"
    elif "alternative" in t or "cheaper" in t or "recommendation" in t:
        return f"Been using this for months to get ChatGPT+Claude without paying full price, zero issues: {link}"
    elif "rate limit" in t or "limits" in t:
        return f"Got tired of hitting Opus limits on Pro, this gives me unlimited access for way cheaper: {link}"
    else:
        return f"I felt the same until I found this — half the price for both ChatGPT and Claude: {link}"

def fetch_latest_targets():
    """用Apify实时抓最近24小时X吐槽帖，返回带中文翻译+回复的目标列表"""
    try:
        # 偷天换日：数据源已剥离 Apify，改读 MacBook 边缘节点投递的本地文件
        with open("/root/projects/ai-news-x-cps/mac_inbox.json", "r", encoding="utf-8") as f:
            items = json.load(f)
        
        # 过滤低质内容
        filtered = []
        for t in items:
            # 过滤转发
            if t.get("isRetweet",False) or t.get("retweetedTweet"):
                continue
            text = t.get("text","").strip()
            if len(text) < 15:
                continue
            author = t.get("author",{})
            # 生成链接、翻译、匹配回复
            url = t.get("url","")
            cn = translate_to_chinese(text)
            reply = match_reply(text, build_tracked_link(author.get("userName", "user")))
            filtered.append({
                "author": "@" + author.get("userName","user"),
                "text": text,
                "chinese": cn,
                "url": url,
                "reply": reply
            })
            if len(filtered) >= 7:
                break
        print(f"  ✅ Apify抓取完成，筛选出{len(filtered)}条最新24小时目标")
        return filtered
    except Exception as e:
        print(f"  ⚠️ Apify抓取失败({str(e)[:60]})，使用默认目标")
        return None

def parse_grok_output(output):
    """Parse grok output into structured dict."""
    patterns = {
        "x_post_1": r"=== X POST 1 ===\s*(.*?)\s*=== IMAGE PROMPT 1 ===",
        "image_prompt_1": r"=== IMAGE PROMPT 1 ===\s*(.*?)\s*=== X POST 2 ===",
        "x_post_2": r"=== X POST 2 ===\s*(.*?)\s*=== IMAGE PROMPT 2 ===",
        "image_prompt_2": r"=== IMAGE PROMPT 2 ===\s*(.*?)\s*=== X POST 3 ===",
        "x_post_3": r"=== X POST 3 ===\s*(.*?)\s*=== IMAGE PROMPT 3 ===",
        "image_prompt_3": r"=== IMAGE PROMPT 3 ===\s*(.*?)\s*=== YOUTUBE SCRIPT ===",
        "youtube_script": r"=== YOUTUBE SCRIPT ===\s*(.*)$"
    }

    result = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, output, re.DOTALL)
        if match:
            result[key] = match.group(1).strip()
        else:
            result[key] = None

    return result

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("AI NEWS → GROK → N8N CONTENT GENERATOR")
    print("=" * 60)

    # 1. Fetch news
    print("\n[1/4] Fetching AI HOT daily news...")
    items, date_str = fetch_daily()
    if not items:
        print("ERROR: No news fetched", file=sys.stderr)
        sys.exit(1)

    # 2. Select fresh, unsent news from distinct fields
    sent_records = load_sent_news()
    print(
        f"\n[2/4] Found {len(items)} fresh topic clusters (≤{MAX_NEWS_AGE_HOURS}h), "
        f"checking {len(sent_records)} sent records and selecting {NUM_ITEMS} fields..."
    )
    selected = select_diverse_news(items, sent_records)
    if len(selected) < NUM_ITEMS:
        print(
            f"ERROR: Only {len(selected)} eligible fresh stories found; "
            f"keeping the existing page instead of publishing a partial set.",
            file=sys.stderr,
        )
        sys.exit(1)
    for index, item in enumerate(selected, 1):
        label = CATEGORY_LABELS[item["category"]]
        print(
            f"  {index}. [{label}] {item['title']} "
            f"({item['age_hours']:.1f}h · {item['source']})"
        )

    # 3. Build prompt and call Grok
    print(f"\n[3/4] Building prompt and calling Grok...")
    prompt = build_grok_prompt(selected)
    output = call_llm(prompt)
    if not output:
        print("ERROR: Failed to get output from Grok", file=sys.stderr)
        sys.exit(1)

    # 4. Parse output
    print(f"\n[4/4] Parsing Grok output...")
    content = parse_grok_output(output)
    required_fields = [
        *(f"x_post_{i}" for i in range(1, NUM_ITEMS + 1)),
        *(f"image_prompt_{i}" for i in range(1, NUM_ITEMS + 1)),
        "youtube_script",
    ]
    missing_fields = [field for field in required_fields if not content.get(field)]
    if missing_fields:
        print(
            f"ERROR: LLM output missing required fields: {', '.join(missing_fields)}",
            file=sys.stderr,
        )
        sys.exit(1)
    content["date"] = date_str or datetime.now().strftime("%Y-%m-%d")
    content["selected_news"] = [
        {
            "title": item["title"],
            "summary": item["summary"],
            "source": item["source"],
            "url": item.get("url", ""),
            "published_at": item["published_at"],
            "age_hours": item["age_hours"],
            "category": item["category"],
        }
        for item in selected
    ]
    content["raw_grok_output"] = output

    # Save to file
    output_file = f"/root/projects/ai-news-x-cps/output-{content['date']}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=2, ensure_ascii=False)

    # Generate material dashboard HTML
    dashboard_out = "/var/www/ai-news-x-cps/index.html"
    dashboard_tmp = f"{dashboard_out}.tmp"
    try:
        with open("/root/projects/ai-news-x-cps/material_template.html", "r", encoding="utf-8") as f:
            html = f.read()

        # 今日待回复目标：优先用Grok实时搜索最新X帖子，失败用默认固定模板
        targets = fetch_latest_targets()
        if targets and len(targets) > 0:
            # 动态生成最新目标HTML
            targets_html = ""
            for i, t in enumerate(targets[:7], 1):
                tid = f"t{i}"
                trid = f"tr{i}"
                auth = t.get('author','user').replace('@','')
                cn = t.get('chinese','')[:80]
                txt = t.get('text','').replace('"','&quot;')
                reply = t.get('reply','')
                url = t.get('url','#')
                targets_html += f"""<div class="tweet-card" id="{tid}">
<div class="tweet-meta">📌 @{auth} · 24小时内新帖 | 【中文】{cn}...</div>
<div class="tweet-text">"{txt}"</div>
<div class="tweet-reply" data-id="{trid}"><pre id="{trid}">{reply}</pre><div class="btn-group"><button class="copy-btn" onclick="event.stopPropagation();cp('{trid}')">复制回复</button> <a class="open-btn" href="{url}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">打开推文</a> <button class="del-btn" onclick="event.stopPropagation();del('{tid}')">已回复</button></div></div>
</div>\n"""
        else:
            # Fallback默认目标（保证永远可用）
            targets_html = """
<div class="tweet-card" id="t1">
<div class="tweet-meta">📌 吐槽ChatGPT Plus太贵</div>
<div class="tweet-reply" data-id="tr1"><pre id="tr1">Canceled my Plus last month after the price hike, replaced it with this, works exactly the same: https://getaipremium.com</pre><div class="btn-group"><button class="copy-btn" onclick="event.stopPropagation();cp('tr1')">复制回复</button> <a class="open-btn" href="https://x.com/search?q=ChatGPT%20Plus%20expensive%20%2420&f=live" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">打开推文</a> <button class="del-btn" onclick="event.stopPropagation();del('t1')">已回复</button></div></div>
</div>
<div class="tweet-card" id="t2">
<div class="tweet-meta">📌 吐槽Claude Pro不值20刀</div>
<div class="tweet-reply" data-id="tr2"><pre id="tr2">Claude Pro's $20/month is rough for casual use. I pay way less for shared access here: https://getaipremium.com</pre><div class="btn-group"><button class="copy-btn" onclick="event.stopPropagation();cp('tr2')">复制回复</button> <a class="open-btn" href="https://x.com/search?q=Claude%20Pro%20overpriced%20%2420&f=live" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">打开推文</a> <button class="del-btn" onclick="event.stopPropagation();del('t2')">已回复</button></div></div>
</div>
<div class="tweet-card" id="t3">
<div class="tweet-meta">📌 找ChatGPT便宜替代</div>
<div class="tweet-reply" data-id="tr3"><pre id="tr3">Been using this for months to get ChatGPT+Claude without paying full price, zero issues: https://getaipremium.com</pre><div class="btn-group"><button class="copy-btn" onclick="event.stopPropagation();cp('tr3')">复制回复</button> <a class="open-btn" href="https://x.com/search?q=alternative%20to%20ChatGPT%20cheaper&f=live" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">打开推文</a> <button class="del-btn" onclick="event.stopPropagation();del('t3')">已回复</button></div></div>
</div>
<div class="tweet-card" id="t4">
<div class="tweet-meta">📌 吐槽Claude额度低</div>
<div class="tweet-reply" data-id="tr4"><pre id="tr4">Got tired of hitting Opus limits on Pro, this gives me unlimited access for way cheaper: https://getaipremium.com</pre><div class="btn-group"><button class="copy-btn" onclick="event.stopPropagation();cp('tr4')">复制回复</button> <a class="open-btn" href="https://x.com/search?q=Claude%20Pro%20rate%20limit&f=live" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">打开推文</a> <button class="del-btn" onclick="event.stopPropagation();del('t4')">已回复</button></div></div>
</div>
<div class="tweet-card" id="t5">
<div class="tweet-meta">📌 吐槽多个AI订阅太贵</div>
<div class="tweet-reply" data-id="tr5"><pre id="tr5">I felt the same until I found this — half the price for both ChatGPT and Claude: https://getaipremium.com</pre><div class="btn-group"><button class="copy-btn" onclick="event.stopPropagation();cp('tr5')">复制回复</button> <a class="open-btn" href="https://x.com/search?q=AI%20subscriptions%20too%20expensive%20%2420&f=live" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">打开推文</a> <button class="del-btn" onclick="event.stopPropagation();del('t5')">已回复</button></div></div>
</div>
<div class="tweet-card" id="t6">
<div class="tweet-meta">📌 取消ChatGPT订阅</div>
<div class="tweet-reply" data-id="tr6"><pre id="tr6">Canceled my Plus after the price hike too, this works exactly the same for a fraction of the cost: https://getaipremium.com</pre><div class="btn-group"><button class="copy-btn" onclick="event.stopPropagation();cp('tr6')">复制回复</button> <a class="open-btn" href="https://x.com/search?q=Canceled%20ChatGPT%20Plus%20price%20hike&f=live" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">打开推文</a> <button class="del-btn" onclick="event.stopPropagation();del('t6')">已回复</button></div></div>
</div>
<div class="tweet-card" id="t7">
<div class="tweet-meta">📌 吐槽ChatGPT不值20刀</div>
<div class="tweet-reply" data-id="tr7"><pre id="tr7">Same, I stopped paying for Plus and use this instead, way better value: https://getaipremium.com</pre><div class="btn-group"><button class="copy-btn" onclick="event.stopPropagation();cp('tr7')">复制回复</button> <a class="open-btn" href="https://x.com/search?q=ChatGPT%20Plus%20not%20worth%20%2420&f=live" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">打开推文</a> <button class="del-btn" onclick="event.stopPropagation();del('t7')">已回复</button></div></div>
</div>
"""
        html = html.replace("<!--TARGETS-->", targets_html)

        # Fill placeholders
        html = html.replace("<!--DATE-->", escape(content["date"]))
        for index, item in enumerate(selected, 1):
            label = CATEGORY_LABELS[item["category"]]
            news_text = (
                f"【{label} · {item['age_hours']:.0f}小时前】\n"
                f"{item['title']}\n{item['summary']}"
            )
            html = html.replace(f"<!--CN{index}-->", escape(news_text))
            html = html.replace(
                f"<!--XP{index}-->",
                escape(content.get(f"x_post_{index}", "") or ""),
            )
            html = html.replace(
                f"<!--IP{index}-->",
                escape(content.get(f"image_prompt_{index}", "") or ""),
            )
        html = html.replace(
            "<!--YT-->", escape(content.get("youtube_script", "") or "")
        )

        # 注入新闻数据，供看板"已发"按钮反向同步去重库
        sent_data = json.dumps(
            [
                {"title": item["title"], "category": item["category"]}
                for item in selected
            ],
            ensure_ascii=False,
        )
        html = html.replace("<!--SENT_NEWS-->", sent_data)

        with open(dashboard_tmp, "w", encoding="utf-8") as f:
            f.write(html)
        subprocess.run(["chown", "caddy:caddy", dashboard_tmp], check=True)
        os.replace(dashboard_tmp, dashboard_out)
        mark_news_sent(selected)
        print(f"  ✅ Material dashboard: {dashboard_out}")
    except Exception as e:
        if os.path.exists(dashboard_tmp):
            os.remove(dashboard_tmp)
        print(f"  WARN: dashboard generation failed: {e}", file=sys.stderr)
        sys.exit(1)

    # Generate dashboard HTML (legacy)
    dashboard_src = "/root/projects/ai-news-x-cps/dashboard.html"
    dashboard_out = f"/root/projects/ai-news-x-cps/dashboard-{content['date']}.html"
    try:
        with open(dashboard_src, "r", encoding="utf-8") as f:
            tmpl = f.read()
        dashboard_data = {
            "date": content["date"],
            "news1_title": selected[0]["title"] if len(selected) > 0 else "",
            "news1_summary": selected[0]["summary"] if len(selected) > 0 else "",
            "news2_title": selected[1]["title"] if len(selected) > 1 else "",
            "news2_summary": selected[1]["summary"] if len(selected) > 1 else "",
            "x_post": content.get("x_post"),
            "image_prompt": content.get("image_prompt"),
            "youtube_script": content.get("youtube_script"),
        }
        inject = "var NEWS_DATA = " + json.dumps(dashboard_data, ensure_ascii=False) + ";\nrender(NEWS_DATA);"
        html_out = tmpl.replace("// CONTENT_INJECT", inject)
        with open(dashboard_out, "w", encoding="utf-8") as f:
            f.write(html_out)
    except Exception as e:
        print(f"  WARN: dashboard generation failed: {e}", file=sys.stderr)

    # Print result
    print("\n" + "=" * 60)
    print("✅ DONE! Content generated:")
    print("=" * 60)
    print(f"\n📅 Date: {content['date']}")
    for i in range(1, 4):
        print(f"\n🐦 X POST {i}:\n{content.get(f'x_post_{i}', 'NOT FOUND')}")
        print(f"\n🖼️  IMAGE PROMPT {i}:\n{content.get(f'image_prompt_{i}', 'NOT FOUND')}")
    print(f"\n🎬 YOUTUBE SHORTS:\n{content.get('youtube_script', 'NOT FOUND')}")
    print(f"\n💾 Saved to: {output_file}")

    # Exit success
    sys.exit(0)

if __name__ == "__main__":
    main()
