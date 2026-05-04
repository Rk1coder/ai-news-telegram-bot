import hashlib
import html
import json
import os
import re
import sys
import time
import traceback
import urllib.parse
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Iterable, List, Optional

import feedparser
import requests
from dateutil import parser as date_parser
from google import genai

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # GitHub Actions uses repository secrets; local .env loading is optional.
    pass


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(ROOT_DIR, "sources.json")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

BULLETIN_MODE = os.getenv("BULLETIN_MODE", "daily").strip().lower()
MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "48"))
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "45"))
BULLETIN_ITEMS = int(os.getenv("BULLETIN_ITEMS", "6"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))

CATEGORY_LABELS = {
    "general_ai": "Genel AI",
    "defense_ai": "Savunma AI / Military AI",
    "counter_uas": "Counter-UAS / Drone Defense",
    "uav_ai": "UAV / Drone Autonomy",
    "robotics": "Robotik",
    "edge_ai": "Edge AI / Computer Vision",
    "turkey_defense": "Türkiye Savunma Sanayi",
    "research_swarm": "Akademik: Sürü Robotik",
    "research_uav": "Akademik: UAV / Drone",
    "research_cv": "Akademik: Computer Vision",
    "research_robotics": "Akademik: Robotik",
    "research_edge_ai": "Akademik: Edge AI",
}

CATEGORY_BASE_SCORE = {
    "defense_ai": 28,
    "counter_uas": 30,
    "uav_ai": 29,
    "robotics": 24,
    "edge_ai": 24,
    "turkey_defense": 31,
    "research_swarm": 27,
    "research_uav": 28,
    "research_cv": 22,
    "research_robotics": 24,
    "research_edge_ai": 22,
    "general_ai": 15,
}

KEYWORD_WEIGHTS = {
    # Savunma / otonom sistemler
    "military ai": 18,
    "defense ai": 18,
    "defence ai": 18,
    "autonomous systems": 16,
    "autonomous system": 14,
    "darpa": 16,
    "nato": 11,
    "counter-uas": 20,
    "counter uas": 20,
    "anti-drone": 18,
    "drone defense": 18,
    "drone defence": 18,
    "electronic warfare": 15,
    "sensor fusion": 13,
    "target tracking": 13,
    "surveillance": 9,
    # UAV / İHA
    "uav": 18,
    "uas": 14,
    "drone": 13,
    "drones": 13,
    "sürü iha": 22,
    "iha": 18,
    "siha": 18,
    "baykar": 18,
    "aselasan": 18,
    "aselsan": 18,
    "tusaş": 17,
    "tusas": 17,
    "stm": 12,
    "havelsan": 15,
    "roketsan": 13,
    "savunma sanayi": 18,
    "otonom sistem": 16,
    # Robotik
    "robotics": 15,
    "robotic": 12,
    "humanoid": 18,
    "embodied ai": 17,
    "robot foundation model": 17,
    "legged robot": 14,
    "quadruped": 13,
    "manipulation": 11,
    # Computer vision / edge AI
    "computer vision": 15,
    "object detection": 14,
    "object tracking": 14,
    "visual tracking": 13,
    "real-time detection": 14,
    "yolo": 16,
    "jetson": 15,
    "edge ai": 16,
    "on-device": 13,
    "inference": 8,
    "hailo": 14,
    "multimodal": 10,
    # AI research / agents
    "ai agent": 12,
    "ai agents": 12,
    "multi-agent": 15,
    "swarm": 18,
    "reinforcement learning": 11,
    "foundation model": 10,
    "vision-language": 11,
    "vla": 10,
    # Akademik sinyal
    "arxiv": 9,
    "paper": 7,
    "benchmark": 8,
    "dataset": 8,
}

NOISE_PATTERNS = [
    r"\bcrypto\b",
    r"\bstock market\b",
    r"\bcelebrity\b",
    r"\bhoroscope\b",
    r"\bgambling\b",
]


@dataclass
class Article:
    title: str
    link: str
    summary: str
    source: str
    category: str
    published_at: str
    kind: str
    trust_score: int
    score: float = 0.0
    matched_keywords: List[str] = None

    def to_prompt_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "source": self.source,
            "category": CATEGORY_LABELS.get(self.category, self.category),
            "published_at": self.published_at,
            "score": round(self.score, 2),
            "matched_keywords": self.matched_keywords or [],
            "summary": shorten(clean_text(self.summary), 700),
            "link": self.link,
            "kind": self.kind,
        }


def clean_text(text: Any) -> str:
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def shorten(text: str, limit: int) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = date_parser.parse(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def iso_or_empty(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.astimezone(timezone.utc).isoformat()


def is_recent(dt: Optional[datetime], max_age_hours: int) -> bool:
    if not dt:
        # Bazı RSS kaynakları tarih vermiyor; tamamen elemek yerine aday olarak bırakıyoruz.
        return True
    return dt >= datetime.now(timezone.utc) - timedelta(hours=max_age_hours)


def load_sources() -> Dict[str, Any]:
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_url(url: str) -> bytes:
    headers = {
        "User-Agent": "AI-Intel-Telegram-Bot/1.0 (+https://github.com/)"
    }
    response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.content


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    content = fetch_url(url)
    return feedparser.parse(content)


def entry_datetime(entry: feedparser.FeedParserDict) -> Optional[datetime]:
    for key in ["published", "updated", "created", "pubDate", "date"]:
        value = entry.get(key)
        dt = parse_datetime(value)
        if dt:
            return dt
    return None


def fetch_rss_sources(sources: List[Dict[str, Any]]) -> List[Article]:
    articles: List[Article] = []
    for src in sources:
        try:
            parsed = fetch_feed(src["url"])
            for entry in parsed.entries[:25]:
                dt = entry_datetime(entry)
                if not is_recent(dt, MAX_AGE_HOURS):
                    continue

                title = clean_text(entry.get("title", ""))
                link = clean_text(entry.get("link", ""))
                content_value = ""
                if entry.get("content"):
                    try:
                        content_value = entry.get("content", [{}])[0].get("value", "")
                    except Exception:
                        content_value = ""
                summary = clean_text(
                    entry.get("summary", "")
                    or entry.get("description", "")
                    or content_value
                )
                if not title or not link:
                    continue

                articles.append(
                    Article(
                        title=title,
                        link=link,
                        summary=summary,
                        source=src.get("name", "RSS"),
                        category=src.get("category", "general_ai"),
                        published_at=iso_or_empty(dt),
                        kind="rss",
                        trust_score=int(src.get("trust_score", 5)),
                        matched_keywords=[],
                    )
                )
        except Exception as exc:
            print(f"[WARN] RSS fetch failed: {src.get('name')} - {exc}", file=sys.stderr)
    return articles


def google_news_url(query: str, language: str, region: str, max_age_hours: int) -> str:
    when_days = max(1, int((max_age_hours + 23) / 24))
    query_with_time = f"({query}) when:{when_days}d"
    encoded = urllib.parse.quote(query_with_time)
    if language == "tr" or region == "TR":
        return f"https://news.google.com/rss/search?q={encoded}&hl=tr&gl=TR&ceid=TR:tr"
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


def fetch_google_news(queries: List[Dict[str, Any]]) -> List[Article]:
    articles: List[Article] = []
    for item in queries:
        try:
            url = google_news_url(
                item["query"],
                item.get("language", "en"),
                item.get("region", "US"),
                MAX_AGE_HOURS,
            )
            parsed = fetch_feed(url)
            for entry in parsed.entries[:15]:
                dt = entry_datetime(entry)
                if not is_recent(dt, MAX_AGE_HOURS):
                    continue
                title = clean_text(entry.get("title", ""))
                link = clean_text(entry.get("link", ""))
                summary = clean_text(entry.get("summary", "") or entry.get("description", ""))
                source = clean_text(entry.get("source", {}).get("title", "Google News")) if isinstance(entry.get("source"), dict) else "Google News"
                if not title or not link:
                    continue
                articles.append(
                    Article(
                        title=title,
                        link=link,
                        summary=summary,
                        source=source or "Google News",
                        category=item.get("category", "general_ai"),
                        published_at=iso_or_empty(dt),
                        kind="google_news",
                        trust_score=int(item.get("trust_score", 5)),
                        matched_keywords=[],
                    )
                )
        except Exception as exc:
            print(f"[WARN] Google News fetch failed: {item.get('query')} - {exc}", file=sys.stderr)
    return articles


def fetch_arxiv(queries: List[Dict[str, Any]]) -> List[Article]:
    articles: List[Article] = []
    for item in queries:
        try:
            search_query = urllib.parse.quote(item["query"])
            url = (
                "https://export.arxiv.org/api/query?"
                f"search_query={search_query}&start=0&max_results=10&sortBy=submittedDate&sortOrder=descending"
            )
            parsed = fetch_feed(url)
            for entry in parsed.entries[:10]:
                dt = entry_datetime(entry)
                if not is_recent(dt, MAX_AGE_HOURS):
                    continue
                title = clean_text(entry.get("title", ""))
                link = clean_text(entry.get("link", ""))
                summary = clean_text(entry.get("summary", ""))
                if not title or not link:
                    continue
                articles.append(
                    Article(
                        title=title,
                        link=link,
                        summary=summary,
                        source="arXiv",
                        category=item.get("category", "research"),
                        published_at=iso_or_empty(dt),
                        kind="arxiv",
                        trust_score=int(item.get("trust_score", 8)),
                        matched_keywords=[],
                    )
                )
            time.sleep(1.0)  # arXiv API'yi nazik kullanmak için kısa bekleme.
        except Exception as exc:
            print(f"[WARN] arXiv fetch failed: {item.get('query')} - {exc}", file=sys.stderr)
    return articles


def normalized_key(text: str) -> str:
    text = text.lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^a-z0-9ığüşöçİĞÜŞÖÇ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def url_key(url: str) -> str:
    try:
        parsed = urllib.parse.urlparse(url)
        clean = parsed.netloc.lower() + parsed.path.lower()
        return hashlib.sha1(clean.encode("utf-8")).hexdigest()
    except Exception:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()


def looks_noisy(article: Article) -> bool:
    blob = f"{article.title} {article.summary}".lower()
    return any(re.search(pattern, blob) for pattern in NOISE_PATTERNS)


def score_article(article: Article) -> Article:
    blob = f"{article.title} {article.summary} {article.source}".lower()
    matched = []
    score = CATEGORY_BASE_SCORE.get(article.category, 10)
    score += article.trust_score * 2

    for keyword, weight in KEYWORD_WEIGHTS.items():
        if keyword.lower() in blob:
            matched.append(keyword)
            score += weight

    dt = parse_datetime(article.published_at)
    if dt:
        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if age_hours <= 12:
            score += 10
        elif age_hours <= 24:
            score += 7
        elif age_hours <= 48:
            score += 4
        elif age_hours <= 168:
            score += 1

    # Başlıkta geçen anahtar kelimeler daha değerli.
    title_lower = article.title.lower()
    for keyword, weight in KEYWORD_WEIGHTS.items():
        if keyword.lower() in title_lower:
            score += min(weight, 12)

    if article.kind == "arxiv":
        score += 8

    if looks_noisy(article):
        score -= 30

    article.score = max(score, 0)
    article.matched_keywords = sorted(set(matched))[:10]
    return article


def deduplicate(articles: Iterable[Article]) -> List[Article]:
    seen_urls = set()
    seen_titles = set()
    unique: List[Article] = []

    for article in articles:
        if not article.title or not article.link:
            continue
        uk = url_key(article.link)
        tk = normalized_key(article.title)
        # Google News başlıkları bazen "- Source" son eki içerir; normalize edip kısaltıyoruz.
        tk_short = " ".join(tk.split()[:14])
        if uk in seen_urls or tk_short in seen_titles:
            continue
        seen_urls.add(uk)
        seen_titles.add(tk_short)
        unique.append(article)

    return unique


def collect_articles() -> List[Article]:
    sources = load_sources()
    articles: List[Article] = []
    articles.extend(fetch_rss_sources(sources.get("rss_sources", [])))
    articles.extend(fetch_google_news(sources.get("google_news_queries", [])))
    articles.extend(fetch_arxiv(sources.get("arxiv_queries", [])))

    articles = deduplicate(articles)
    articles = [score_article(a) for a in articles]
    articles.sort(key=lambda a: a.score, reverse=True)
    return articles[:MAX_CANDIDATES]


def article_payload(article: Article, article_id: int) -> Dict[str, Any]:
    data = article.to_prompt_dict()
    data["id"] = article_id
    return data


def build_prompt(articles: List[Article]) -> str:
    now_tr = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
    data = [article_payload(a, idx) for idx, a in enumerate(articles, 1)]
    mode_label = "haftalık derin trend raporu" if BULLETIN_MODE == "weekly" else "günlük teknoloji istihbarat bülteni"
    item_limit = BULLETIN_ITEMS

    if BULLETIN_MODE == "weekly":
        task = f"""
Haftalık AI + savunma sanayi + robotik + UAV + edge AI trend raporu için yapılandırılmış JSON üret.
En önemli {item_limit} gelişmeyi seç.
"""
        expected = "weekly"
    else:
        task = f"""
Günlük AI + savunma sanayi + robotik + UAV + edge AI bülteni için yapılandırılmış JSON üret.
En önemli {item_limit} gelişmeyi seç.
"""
        expected = "daily"

    return f"""
Sen Rabia için çalışan teknik bir AI haber analisti gibi davranıyorsun.
Rabia'nın ilgi alanları: savunma sanayi, UAV/İHA, computer vision, edge AI, robotik, sürü robotik, autonomous systems, counter-UAS, NVIDIA Jetson/Hailo, YOLO/object tracking, medikal AI ve OnkoNixAI.

Görev: {mode_label}
Tarih: {now_tr}
{task}

ÇOK ÖNEMLİ ÇIKTI KURALLARI:
- Sadece geçerli JSON döndür. Markdown, açıklama, kod bloğu, ```json kullanma.
- Link üretme; sadece seçtiğin haberin id değerini kullan. Linki sistem kendisi ekleyecek.
- item_id alanı aday haberlerdeki id ile aynı olmalı.
- Cümleler kısa ve Telegram için okunabilir olsun.
- Her özet en fazla 220 karakter olsun.
- Her "why_it_matters" en fazla 180 karakter olsun.
- Her "technical_note" en fazla 200 karakter olsun.
- Radar maddeleri en fazla 110 karakter olsun.
- Aynı konuyu tekrar etme.
- Belirsizse kesin hüküm verme; "takip edilmeli", "erken sinyal" gibi ifadeler kullan.
- Savunma/hassas konularda operasyonel talimat, silahlandırma veya zarar verme yönergesi yazma; sadece yüksek seviyeli analiz ver.

Beklenen JSON şeması:
{{
  "type": "{expected}",
  "title": "Günlük AI + Savunma + Robotik Radarı",
  "radar": ["madde 1", "madde 2", "madde 3", "madde 4", "madde 5"],
  "items": [
    {{
      "item_id": 1,
      "category": "Counter-UAS / Drone Defense",
      "title": "kısa başlık",
      "summary": "2 cümleyi geçmeyen kısa özet",
      "why_it_matters": "kısa önem analizi",
      "technical_note": "İHA/robotik/edge AI açısından teknik çıkarım",
      "confidence": "yüksek|orta|düşük"
    }}
  ],
  "trend_comment": "Bugünün/haftanın ana trend yorumu. En fazla 450 karakter.",
  "follow_keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"]
}}

Aday haberler ve makaleler JSON:
{json.dumps(data, ensure_ascii=False, indent=2)}
""".strip()


def extract_json_object(text: str) -> Dict[str, Any]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def generate_structured_bulletin(articles: List[Article]) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY eksik. GitHub Secrets içine ekleyin.")
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = build_prompt(articles)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )
    text = getattr(response, "text", None) or str(response)
    return extract_json_object(text)


def category_icon(category: str) -> str:
    c = (category or "").lower()
    if "counter" in c or "drone defense" in c:
        return "🛡️"
    if "uav" in c or "drone" in c or "iha" in c:
        return "🚁"
    if "robot" in c or "humanoid" in c:
        return "🤖"
    if "edge" in c or "vision" in c or "yolo" in c:
        return "👁️"
    if "akademik" in c or "arxiv" in c or "research" in c:
        return "📄"
    if "türkiye" in c or "turkey" in c or "savunma" in c:
        return "🇹🇷"
    return "•"


def safe_html(text: Any, limit: int = None) -> str:
    value = clean_text(text)
    if limit:
        value = shorten(value, limit)
    return html.escape(value, quote=False)


def article_map(articles: List[Article]) -> Dict[int, Article]:
    return {idx: article for idx, article in enumerate(articles, 1)}


def format_bulletin_html(payload: Dict[str, Any], articles: List[Article]) -> str:
    now_tr = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
    by_id = article_map(articles)
    mode_title = "Haftalık AI + Savunma + Robotik Raporu" if BULLETIN_MODE == "weekly" else "Günlük AI + Savunma + Robotik Radarı"

    lines: List[str] = []
    lines.append(f"<b>🤖 {safe_html(payload.get('title') or mode_title)}</b>")
    lines.append(f"<i>{now_tr} • {len(payload.get('items', []))} seçili gelişme</i>")
    lines.append("")

    radar = payload.get("radar") or []
    if radar:
        lines.append("<b>⚡ Kısa radar</b>")
        for point in radar[:5]:
            lines.append(f"• {safe_html(point, 120)}")
        lines.append("")

    items = payload.get("items") or []
    lines.append("<b>📌 Öne çıkan gelişmeler</b>")
    lines.append("")

    for index, item in enumerate(items[:BULLETIN_ITEMS], 1):
        try:
            item_id = int(item.get("item_id"))
        except Exception:
            item_id = 0
        article = by_id.get(item_id)
        category = item.get("category") or (CATEGORY_LABELS.get(article.category, article.category) if article else "Genel")
        icon = category_icon(category)
        title = item.get("title") or (article.title if article else "Başlık yok")
        source = article.source if article else "Kaynak"
        link = article.link if article else ""
        score = round(article.score, 1) if article else None
        confidence = safe_html(item.get("confidence", "orta"), 20)

        lines.append(f"<b>{index}. {icon} {safe_html(title, 115)}</b>")
        if score is not None:
            lines.append(f"<b>Kategori:</b> {safe_html(category, 70)}  |  <b>Skor:</b> {score}  |  <b>Güven:</b> {confidence}")
        else:
            lines.append(f"<b>Kategori:</b> {safe_html(category, 70)}  |  <b>Güven:</b> {confidence}")
        lines.append(f"<b>Özet:</b> {safe_html(item.get('summary'), 260)}")
        lines.append(f"<b>Neden önemli:</b> {safe_html(item.get('why_it_matters'), 220)}")
        lines.append(f"<b>Teknik not:</b> {safe_html(item.get('technical_note'), 240)}")
        if link:
            lines.append(f"<b>Kaynak:</b> <a href=\"{html.escape(link, quote=True)}\">{safe_html(source, 60)}</a>")
        lines.append("")

    trend = payload.get("trend_comment")
    if trend:
        lines.append("<b>🧭 Stratejik trend yorumu</b>")
        lines.append(safe_html(trend, 520))
        lines.append("")

    keywords = payload.get("follow_keywords") or []
    if keywords:
        compact = ", ".join([clean_text(k) for k in keywords[:8]])
        lines.append(f"<b>🔎 Takip anahtarları:</b> {safe_html(compact, 220)}")

    return "\n".join(lines).strip()


def generate_bulletin(articles: List[Article]) -> str:
    payload = generate_structured_bulletin(articles)
    return format_bulletin_html(payload, articles)


def send_telegram_message(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik.")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = split_message(message, 3600)

    for chunk in chunks:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        time.sleep(0.5)


def split_message(message: str, max_len: int) -> List[str]:
    if len(message) <= max_len:
        return [message]

    blocks = message.split("\n\n")
    chunks: List[str] = []
    current = ""

    for block in blocks:
        candidate = block if not current else current + "\n\n" + block
        if len(candidate) <= max_len:
            current = candidate
            continue

        if current:
            chunks.append(current)
            current = ""

        if len(block) <= max_len:
            current = block
        else:
            # Çok uzun tek blok varsa HTML linkleri kırmamak için görünür metni sadeleştiriyoruz.
            plain = re.sub(r"<a href=\"[^\"]+\">([^<]+)</a>", r"\1", block)
            plain = re.sub(r"</?b>|</?i>", "", plain)
            while len(plain) > max_len:
                chunks.append(html.escape(plain[:max_len - 20]) + "…")
                plain = plain[max_len - 20:]
            current = html.escape(plain)

    if current:
        chunks.append(current)
    return chunks


def fallback_bulletin(articles: List[Article]) -> str:
    now_tr = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
    lines = [f"<b>🤖 AI + Savunma + Robotik Radarı — {now_tr}</b>", "", "Gemini özetleme çalışmadı; skorlanmış aday listesi gönderiliyor.", ""]
    for idx, article in enumerate(articles[:BULLETIN_ITEMS], 1):
        category = CATEGORY_LABELS.get(article.category, article.category)
        lines.extend([
            f"<b>{idx}. {category_icon(category)} {safe_html(article.title, 120)}</b>",
            f"<b>Kategori:</b> {safe_html(category, 70)} | <b>Skor:</b> {round(article.score, 1)}",
            f"<b>Özet:</b> {safe_html(article.summary, 280)}",
            f"<b>Kaynak:</b> <a href=\"{html.escape(article.link, quote=True)}\">{safe_html(article.source, 60)}</a>",
            "",
        ])
    return "\n".join(lines).strip()


def main() -> None:
    try:
        articles = collect_articles()
        if not articles:
            send_telegram_message("Bugün AI + savunma + robotik alanında yeni aday haber bulunamadı.")
            return

        try:
            bulletin = generate_bulletin(articles)
        except Exception as gemini_error:
            print(f"[WARN] Gemini failed, using fallback: {gemini_error}", file=sys.stderr)
            bulletin = fallback_bulletin(articles)

        send_telegram_message(bulletin)
        print(f"Sent bulletin with {len(articles)} candidate items.")
    except Exception as exc:
        err = "⚠️ AI haber botu hata aldı.\n\n" + shorten(traceback.format_exc(), 3000)
        print(err, file=sys.stderr)
        try:
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                send_telegram_message(err)
        finally:
            raise exc


if __name__ == "__main__":
    main()
