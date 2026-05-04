import hashlib
import html
import json
import os
import re
import sys
import time
import traceback
import urllib.parse
from dataclasses import dataclass, field
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
    pass


ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCES_FILE = os.path.join(ROOT_DIR, "sources.json")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
# 503 / high-demand durumları için model yedekleri. Örnek: gemini-2.5-flash-lite,gemini-2.0-flash
GEMINI_FALLBACK_MODELS = [m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash-lite,gemini-2.0-flash").split(",") if m.strip()]
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "3"))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()  # Opsiyonel; rate-limit için önerilir
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()  # Opsiyonel; HuggingFace API bazı endpointlerde token isteyebilir

BULLETIN_MODE = os.getenv("BULLETIN_MODE", "daily").strip().lower()
MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "48"))
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "35"))
BULLETIN_ITEMS = int(os.getenv("BULLETIN_ITEMS", "7"))
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
    "hf_model": "🤗 HuggingFace: Yeni Model",
    "hf_paper": "🤗 HuggingFace: Günün Makalesi",
    "github_trending": "🐙 GitHub: Trend Repo",
    "github_release": "🚀 GitHub: Kritik Release",
    "papers_with_code": "📊 Papers With Code: SOTA",
    "semantic_scholar": "🎓 Semantic Scholar: Etkili Makale",
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
    "hf_model": 26,
    "hf_paper": 28,
    "github_trending": 22,
    "github_release": 30,
    "papers_with_code": 27,
    "semantic_scholar": 25,
}

KEYWORD_WEIGHTS = {
    # Savunma / otonom sistemler
    "military ai": 18, "defense ai": 18, "defence ai": 18,
    "autonomous systems": 16, "autonomous system": 14,
    "darpa": 16, "nato": 11,
    "counter-uas": 20, "counter uas": 20,
    "anti-drone": 18, "drone defense": 18, "drone defence": 18,
    "electronic warfare": 15, "sensor fusion": 13,
    "target tracking": 13, "surveillance": 9,
    # UAV / İHA
    "uav": 18, "uas": 14, "drone": 13, "drones": 13,
    "sürü iha": 22, "iha": 18, "siha": 18,
    "baykar": 18, "aselasan": 18, "aselsan": 18,
    "tusaş": 17, "tusas": 17, "stm": 12, "havelsan": 15,
    "roketsan": 13, "savunma sanayi": 18, "otonom sistem": 16,
    # Robotik
    "robotics": 15, "robotic": 12, "humanoid": 18,
    "embodied ai": 17, "robot foundation model": 17,
    "legged robot": 14, "quadruped": 13, "manipulation": 11,
    # Computer vision / edge AI
    "computer vision": 15, "object detection": 14,
    "object tracking": 14, "visual tracking": 13,
    "real-time detection": 14, "yolo": 16,
    "jetson": 15, "edge ai": 16, "on-device": 13,
    "inference": 8, "hailo": 14, "multimodal": 10,
    "onnx": 10, "tensorrt": 12, "tflite": 10, "openvino": 10,
    # AI research / agents
    "ai agent": 12, "ai agents": 12,
    "multi-agent": 15, "swarm": 18,
    "reinforcement learning": 11, "foundation model": 10,
    "vision-language": 11, "vla": 10,
    "diffusion": 9, "transformer": 8,
    # HuggingFace / model sinyal kelimeleri
    "fine-tuned": 10, "quantized": 12, "gguf": 11,
    "lora": 10, "peft": 9, "benchmark": 8,
    "open source": 7, "open-source": 7,
    # GitHub sinyal kelimeleri
    "release": 8, "v2": 6, "v3": 6,
    "real-time": 12, "deployment": 9,
    # Akademik sinyal
    "arxiv": 9, "paper": 7, "dataset": 8,
    "state-of-the-art": 14, "sota": 14,
}

NOISE_PATTERNS = [
    r"\bcrypto\b", r"\bstock market\b", r"\bcelebrity\b",
    r"\bhoroscope\b", r"\bgambling\b",
]

# GitHub Releases: takip edilecek kritik repolar
GITHUB_WATCH_REPOS = [
    {"owner": "ultralytics", "repo": "ultralytics", "category": "edge_ai", "trust_score": 9},
    {"owner": "ultralytics", "repo": "yolov5", "category": "edge_ai", "trust_score": 8},
    {"owner": "hailo-ai", "repo": "hailo-rpi5-examples", "category": "edge_ai", "trust_score": 8},
    {"owner": "NVIDIA", "repo": "TensorRT-LLM", "category": "edge_ai", "trust_score": 9},
    {"owner": "NVIDIA-AI-IOT", "repo": "deepstream_python_apps", "category": "edge_ai", "trust_score": 7},
    {"owner": "roboflow", "repo": "supervision", "category": "research_cv", "trust_score": 8},
    {"owner": "PaddlePaddle", "repo": "PaddleDetection", "category": "research_cv", "trust_score": 7},
    {"owner": "openai", "repo": "openai-python", "category": "general_ai", "trust_score": 8},
    {"owner": "huggingface", "repo": "transformers", "category": "general_ai", "trust_score": 9},
    {"owner": "huggingface", "repo": "diffusers", "category": "general_ai", "trust_score": 8},
    {"owner": "ggerganov", "repo": "llama.cpp", "category": "edge_ai", "trust_score": 9},
    {"owner": "open-rmf", "repo": "rmf", "category": "robotics", "trust_score": 7},
    {"owner": "google-deepmind", "repo": "mujoco", "category": "research_robotics", "trust_score": 8},
    {"owner": "microsoft", "repo": "autogen", "category": "general_ai", "trust_score": 8},
    {"owner": "voxel51", "repo": "fiftyone", "category": "research_cv", "trust_score": 7},
]

# HuggingFace: model tag filtreleri (trending modellerde bu taglardan biri varsa dahil et)
HF_RELEVANT_TAGS = {
    "object-detection", "image-classification", "image-segmentation",
    "video-classification", "depth-estimation", "keypoint-detection",
    "robotics", "reinforcement-learning", "text-to-image",
    "visual-question-answering", "zero-shot-object-detection",
    "autonomous-driving",
}

# Papers With Code: takip edilecek task'lar
ENABLE_PWC = os.getenv("ENABLE_PWC", "false").strip().lower() in {"1", "true", "yes", "on"}

PWC_TASKS = [
    "object-detection",
    "multi-object-tracking",
    "small-object-detection",
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
    matched_keywords: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_prompt_dict(self) -> Dict[str, Any]:
        d = {
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
        if self.extra:
            d["extra"] = self.extra
        return d


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def clean_text(text: Any) -> str:
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_text_preserve_lines(text: Any) -> str:
    """Gemini/Telegram çıktısında satır sonlarını koruyarak hafif temizlik yapar."""
    if text is None:
        return ""
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    # Her satırın içindeki fazla boşlukları düzelt, ama paragraf yapısını bozma.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


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
        return True
    return dt >= datetime.now(timezone.utc) - timedelta(hours=max_age_hours)


def load_sources() -> Dict[str, Any]:
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_url(url: str, headers: Optional[Dict] = None) -> bytes:
    _headers = {"User-Agent": "AI-Intel-Telegram-Bot/2.0 (+https://github.com/)"}
    if headers:
        _headers.update(headers)
    response = requests.get(url, headers=_headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.content


def fetch_json(url: str, headers: Optional[Dict] = None) -> Any:
    _headers = {"User-Agent": "AI-Intel-Telegram-Bot/2.0 (+https://github.com/)"}
    if headers:
        _headers.update(headers)
    response = requests.get(url, headers=_headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    try:
        return response.json()
    except ValueError as exc:
        preview = response.text[:160].replace("\n", " ")
        raise ValueError(f"JSON parse failed. content-type={content_type}, preview={preview}") from exc


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


def github_headers() -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


# ---------------------------------------------------------------------------
# Source fetchers — original
# ---------------------------------------------------------------------------

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
                articles.append(Article(
                    title=title, link=link, summary=summary,
                    source=src.get("name", "RSS"),
                    category=src.get("category", "general_ai"),
                    published_at=iso_or_empty(dt), kind="rss",
                    trust_score=int(src.get("trust_score", 5)),
                ))
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
    max_queries = int(os.getenv("GOOGLE_NEWS_MAX_QUERIES", str(len(queries))))
    delay = float(os.getenv("GOOGLE_NEWS_DELAY_SECONDS", "0.4"))

    for item in queries[:max_queries]:
        try:
            time.sleep(delay)
            url = google_news_url(
                item["query"], item.get("language", "en"),
                item.get("region", "US"), MAX_AGE_HOURS,
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
                articles.append(Article(
                    title=title, link=link, summary=summary,
                    source=source or "Google News",
                    category=item.get("category", "general_ai"),
                    published_at=iso_or_empty(dt), kind="google_news",
                    trust_score=int(item.get("trust_score", 5)),
                ))
        except Exception as exc:
            print(f"[WARN] Google News fetch failed: {item.get('query')} - {exc}", file=sys.stderr)
    return articles


def fetch_arxiv(queries: List[Dict[str, Any]]) -> List[Article]:
    articles: List[Article] = []
    # arXiv API 429 vermemesi için her run'da query sayısını sınırlıyoruz.
    max_queries = int(os.getenv("ARXIV_MAX_QUERIES", "4"))
    delay = float(os.getenv("ARXIV_DELAY_SECONDS", "3.5"))

    for item in queries[:max_queries]:
        search_query_raw = item["query"]
        for attempt in range(2):
            try:
                time.sleep(delay)
                search_query = urllib.parse.quote(search_query_raw)
                url = (
                    "https://export.arxiv.org/api/query?"
                    f"search_query={search_query}&start=0&max_results=5"
                    "&sortBy=submittedDate&sortOrder=descending"
                )
                parsed = fetch_feed(url)
                for entry in parsed.entries[:5]:
                    dt = entry_datetime(entry)
                    if not is_recent(dt, MAX_AGE_HOURS * 3):
                        continue
                    title = clean_text(entry.get("title", ""))
                    link = clean_text(entry.get("link", ""))
                    summary = clean_text(entry.get("summary", ""))
                    if not title or not link:
                        continue
                    articles.append(Article(
                        title=title, link=link, summary=summary,
                        source="arXiv", category=item.get("category", "research"),
                        published_at=iso_or_empty(dt), kind="arxiv",
                        trust_score=int(item.get("trust_score", 8)),
                    ))
                break
            except Exception as exc:
                msg = str(exc)
                if "429" in msg and attempt == 0:
                    print(f"[WARN] arXiv rate-limited, retrying slowly: {search_query_raw}", file=sys.stderr)
                    time.sleep(delay * 3)
                    continue
                print(f"[WARN] arXiv fetch failed: {search_query_raw} - {exc}", file=sys.stderr)
                break
    return articles

# ---------------------------------------------------------------------------
# NEW: HuggingFace
# ---------------------------------------------------------------------------

def fetch_hf_trending_models() -> List[Article]:
    """
    HuggingFace trending modelleri çeker. API key gerekmez.
    Sorgulanan endpoint: huggingface.co/api/trending-repos
    """
    articles: List[Article] = []
    try:
        headers = {"Authorization": f"Bearer {HF_TOKEN}"} if HF_TOKEN else None
        data = fetch_json(
            "https://huggingface.co/api/trending-repos?limit=30&type=model",
            headers=headers,
        )
        repos = data if isinstance(data, list) else data.get("recentlyTrending", [])
        now = datetime.now(timezone.utc)

        for repo in repos[:30]:
            repo_id = repo.get("id") or repo.get("repoData", {}).get("id") or ""
            if not repo_id:
                # Try nested structure
                repo_id = (repo.get("repoData") or {}).get("id", "")
            if not repo_id:
                continue

            tags = []
            repo_data = repo.get("repoData") or repo
            pipeline_tag = repo_data.get("pipeline_tag", "") or ""
            tags = list(repo_data.get("tags") or [])
            if pipeline_tag:
                tags.append(pipeline_tag)

            # Sadece ilgili tagları olan modelleri al
            relevant = HF_RELEVANT_TAGS.intersection(set(t.lower() for t in tags))

            downloads = repo_data.get("downloads", 0) or 0
            likes = repo_data.get("likes", 0) or 0

            # Filtreleme: ya ilgili tag var, ya da yeterince popüler ve ML modeli
            if not relevant and downloads < 5000:
                continue

            title = f"🤗 HF Model Trend: {repo_id}"
            link = f"https://huggingface.co/{repo_id}"
            card_data = repo_data.get("cardData") or {}
            summary_parts = []
            if pipeline_tag:
                summary_parts.append(f"Task: {pipeline_tag}")
            if tags:
                summary_parts.append(f"Tags: {', '.join(tags[:6])}")
            if downloads:
                summary_parts.append(f"Downloads (month): {downloads:,}")
            if likes:
                summary_parts.append(f"Likes: {likes:,}")
            if card_data.get("base_model"):
                summary_parts.append(f"Base model: {card_data['base_model']}")

            summary = " | ".join(summary_parts)

            articles.append(Article(
                title=title, link=link, summary=summary,
                source="HuggingFace Trending",
                category="hf_model",
                published_at=iso_or_empty(now),
                kind="hf_model",
                trust_score=8,
                extra={
                    "downloads": downloads,
                    "likes": likes,
                    "pipeline_tag": pipeline_tag,
                    "relevant_tags": list(relevant),
                },
            ))
    except Exception as exc:
        print(f"[WARN] HuggingFace trending models failed: {exc}", file=sys.stderr)
    return articles


def fetch_hf_daily_papers() -> List[Article]:
    """
    HuggingFace günün makalelerini çeker (papers.huggingface.co feed).
    """
    articles: List[Article] = []
    try:
        data = fetch_json("https://huggingface.co/api/daily_papers?limit=20")
        papers = data if isinstance(data, list) else []

        for paper in papers[:20]:
            paper_info = paper.get("paper") or paper
            arxiv_id = paper_info.get("id", "") or paper_info.get("arxivId", "")
            title = clean_text(paper_info.get("title", ""))
            if not title:
                continue

            upvotes = paper.get("numComments", 0) or paper_info.get("upvotes", 0)
            link = f"https://huggingface.co/papers/{arxiv_id}" if arxiv_id else "https://huggingface.co/papers"
            summary = clean_text(paper_info.get("summary", "") or paper_info.get("abstract", ""))
            published_str = paper.get("publishedAt") or paper_info.get("publishedAt", "")
            dt = parse_datetime(published_str)
            if not is_recent(dt, MAX_AGE_HOURS * 2):  # HF papers için daha geniş pencere
                continue

            authors = [a.get("name", "") for a in (paper_info.get("authors") or [])[:3]]

            articles.append(Article(
                title=f"📄 HF Paper: {title}",
                link=link, summary=summary,
                source="HuggingFace Papers",
                category="hf_paper",
                published_at=iso_or_empty(dt),
                kind="hf_paper",
                trust_score=9,
                extra={
                    "upvotes": upvotes,
                    "arxiv_id": arxiv_id,
                    "authors": authors,
                },
            ))
    except Exception as exc:
        print(f"[WARN] HuggingFace daily papers failed: {exc}", file=sys.stderr)
    return articles


# ---------------------------------------------------------------------------
# NEW: GitHub Trending
# ---------------------------------------------------------------------------

def fetch_github_trending() -> List[Article]:
    """
    GitHub Trending sayfasını çeker (web scraping, resmi API yok).
    """
    articles: List[Article] = []
    urls = [
        ("https://github.com/trending/python?since=daily", "Python"),
        ("https://github.com/trending/c%2B%2B?since=daily", "C++"),
        ("https://github.com/trending?since=daily", "All"),
    ]
    # Filtre kelimeleri — AI/robotics/vision ile alakalı olanlara odaklan
    filter_keywords = {
        "robot", "drone", "uav", "vision", "detection", "yolo", "ai", "ml",
        "deep", "neural", "llm", "model", "inference", "edge", "jetson",
        "hailo", "cuda", "tracking", "slam", "autonomous", "nav", "control",
        "simulation", "gym", "rl", "reinforcement", "diffusion", "transformer",
        "segment", "point cloud", "lidar", "3d",
    }
    now = datetime.now(timezone.utc)

    for url, lang in urls:
        try:
            content = fetch_url(url).decode("utf-8", errors="ignore")
            # Basit regex parse — tam HTML parse kütüphanesi eklemekten kaçınmak için
            repo_blocks = re.findall(
                r'<article[^>]*class="[^"]*Box-row[^"]*"[^>]*>(.*?)</article>',
                content, re.DOTALL
            )
            for block in repo_blocks[:25]:
                # Repo adı
                name_match = re.search(r'href="/([^"]+)"[^>]*>\s*([^<]+)\s*</a>', block)
                if not name_match:
                    continue
                repo_path = name_match.group(1).strip()
                if repo_path.count("/") != 1:
                    continue  # Sadece owner/repo formatı

                # Açıklama
                desc_match = re.search(r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>(.*?)</p>', block, re.DOTALL)
                description = clean_text(desc_match.group(1)) if desc_match else ""

                # Stars
                stars_match = re.search(r'([\d,]+)\s*stars', block)
                stars = int(stars_match.group(1).replace(",", "")) if stars_match else 0

                # Bugün kazanılan yıldız
                today_match = re.search(r'([\d,]+)\s*stars today', block)
                stars_today = int(today_match.group(1).replace(",", "")) if today_match else 0

                # Filtrele
                searchable = f"{repo_path} {description}".lower()
                if not any(kw in searchable for kw in filter_keywords):
                    continue

                link = f"https://github.com/{repo_path}"
                title = f"⭐ GitHub Trend: {repo_path}"
                summary = description
                if stars_today:
                    summary += f" | +{stars_today} stars today"
                if stars:
                    summary += f" | Total: {stars:,}★"
                if lang != "All":
                    summary += f" | Lang: {lang}"

                articles.append(Article(
                    title=title, link=link, summary=summary,
                    source="GitHub Trending",
                    category="github_trending",
                    published_at=iso_or_empty(now),
                    kind="github_trending",
                    trust_score=7,
                    extra={"stars": stars, "stars_today": stars_today, "language": lang},
                ))
        except Exception as exc:
            print(f"[WARN] GitHub trending fetch failed ({lang}): {exc}", file=sys.stderr)

    return articles


# ---------------------------------------------------------------------------
# NEW: GitHub Releases
# ---------------------------------------------------------------------------

def fetch_github_releases() -> List[Article]:
    """
    Kritik repoların son release'lerini GitHub API ile çeker.
    GITHUB_TOKEN opsiyonel ama rate-limit için önerilir.
    """
    articles: List[Article] = []
    headers = github_headers()

    for repo_info in GITHUB_WATCH_REPOS:
        owner = repo_info["owner"]
        repo = repo_info["repo"]
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=3"
            releases = fetch_json(url, headers=headers)
            if not isinstance(releases, list):
                continue
            for release in releases[:3]:
                published_str = release.get("published_at") or release.get("created_at", "")
                dt = parse_datetime(published_str)
                if not is_recent(dt, MAX_AGE_HOURS * 3):  # Release'ler için daha geniş pencere
                    break  # releases tarih sıralıdır, daha eskisi olmaz

                tag = release.get("tag_name", "")
                name = release.get("name") or tag
                body = clean_text(release.get("body", ""))
                html_url = release.get("html_url", f"https://github.com/{owner}/{repo}/releases")
                prerelease = release.get("prerelease", False)

                if prerelease:
                    continue  # Pre-release'leri atla

                title = f"🚀 Release: {owner}/{repo} {tag}"
                summary = shorten(body, 500) if body else f"{name} yayınlandı."

                articles.append(Article(
                    title=title, link=html_url, summary=summary,
                    source=f"GitHub: {owner}/{repo}",
                    category=repo_info.get("category", "github_release"),
                    published_at=iso_or_empty(dt),
                    kind="github_release",
                    trust_score=int(repo_info.get("trust_score", 8)),
                    extra={"tag": tag, "repo": f"{owner}/{repo}"},
                ))
            time.sleep(0.3)
        except requests.exceptions.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status == 404:
                print(f"[INFO] GitHub releases skipped: {owner}/{repo} has no releases or repo moved.", file=sys.stderr)
            else:
                print(f"[WARN] GitHub release fetch failed: {owner}/{repo} - {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"[WARN] GitHub release fetch failed: {owner}/{repo} - {exc}", file=sys.stderr)

    return articles


# ---------------------------------------------------------------------------
# NEW: Papers With Code
# ---------------------------------------------------------------------------

def fetch_papers_with_code(tasks: List[str]) -> List[Article]:
    """
    Papers With Code API'sinden en son SOTA makalelerini çeker.
    https://paperswithcode.com/api/v1/papers/
    """
    articles: List[Article] = []
    base_url = "https://paperswithcode.com/api/v1/papers/"

    for task in tasks:
        try:
            url = f"{base_url}?task={urllib.parse.quote(task)}&ordering=-published&items_per_page=5"
            data = fetch_json(url)
            results = data.get("results") or []

            for paper in results[:5]:
                title = clean_text(paper.get("title", ""))
                if not title:
                    continue
                abstract = clean_text(paper.get("abstract", ""))
                arxiv_id = paper.get("arxiv_id", "")
                url_paper = paper.get("url_pdf") or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "")
                if not url_paper:
                    url_paper = f"https://paperswithcode.com/paper/{paper.get('id', '')}"
                published_str = paper.get("published", "")
                dt = parse_datetime(published_str)
                if not is_recent(dt, MAX_AGE_HOURS * 4):
                    continue

                github_link = ""
                repos = paper.get("repositories", [])
                if repos and isinstance(repos, list):
                    github_link = repos[0].get("url", "") if repos else ""

                stars_sum = sum(r.get("stars", 0) for r in repos if isinstance(r, dict))

                summary = shorten(abstract, 500)
                if github_link:
                    summary += f" | Code: {github_link}"
                if stars_sum:
                    summary += f" | Repo stars: {stars_sum:,}"

                articles.append(Article(
                    title=f"📊 PWC [{task}]: {title}",
                    link=url_paper, summary=summary,
                    source="Papers With Code",
                    category="papers_with_code",
                    published_at=iso_or_empty(dt),
                    kind="papers_with_code",
                    trust_score=8,
                    extra={"task": task, "has_code": bool(github_link), "repo_stars": stars_sum},
                ))
            time.sleep(0.5)
        except Exception as exc:
            print(f"[WARN] Papers With Code failed ({task}): {exc}", file=sys.stderr)

    return articles


# ---------------------------------------------------------------------------
# NEW: Semantic Scholar
# ---------------------------------------------------------------------------

def fetch_semantic_scholar(queries: List[Dict[str, Any]]) -> List[Article]:
    """
    Semantic Scholar API ile son makaleleri çeker.
    Citation count + influence score ile önem sıralı.
    https://api.semanticscholar.org/graph/v1/paper/search
    """
    articles: List[Article] = []
    base_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    fields = "title,abstract,year,authors,citationCount,influentialCitationCount,externalIds,publicationDate,openAccessPdf"
    max_queries = int(os.getenv("SEMANTIC_SCHOLAR_MAX_QUERIES", "2"))
    delay = float(os.getenv("SEMANTIC_SCHOLAR_DELAY_SECONDS", "4.0"))

    for item in queries[:max_queries]:
        try:
            time.sleep(delay)
            params = {
                "query": item["query"],
                "fields": fields,
                "limit": 5,
                "sort": "citationCount",
            }
            if item.get("year_filter"):
                params["year"] = item["year_filter"]

            url = f"{base_url}?{urllib.parse.urlencode(params)}"
            data = fetch_json(url)
            papers = data.get("data") or []

            for paper in papers[:8]:
                title = clean_text(paper.get("title", ""))
                if not title:
                    continue
                abstract = clean_text(paper.get("abstract", "") or "")
                citation_count = paper.get("citationCount", 0) or 0
                influential = paper.get("influentialCitationCount", 0) or 0

                # Çok alıntılı ama çok eski makaleleri filtrele
                pub_date = paper.get("publicationDate", "")
                dt = parse_datetime(pub_date)
                if dt and not is_recent(dt, MAX_AGE_HOURS * 24):  # 1 ay
                    if citation_count < 50:  # Yeni ve az alıntılı ise atla
                        continue

                external_ids = paper.get("externalIds") or {}
                arxiv_id = external_ids.get("ArXiv", "")
                doi = external_ids.get("DOI", "")

                if arxiv_id:
                    link = f"https://arxiv.org/abs/{arxiv_id}"
                elif doi:
                    link = f"https://doi.org/{doi}"
                else:
                    paper_id = paper.get("paperId", "")
                    link = f"https://www.semanticscholar.org/paper/{paper_id}"

                pdf_link = ""
                if paper.get("openAccessPdf"):
                    pdf_link = paper["openAccessPdf"].get("url", "")

                authors = [a.get("name", "") for a in (paper.get("authors") or [])[:3]]
                summary_parts = [abstract[:400]] if abstract else []
                summary_parts.append(f"Cited by: {citation_count} | Influential: {influential}")
                if authors:
                    summary_parts.append(f"Authors: {', '.join(authors)}")
                if pdf_link:
                    summary_parts.append(f"PDF: {pdf_link}")

                articles.append(Article(
                    title=f"🎓 S2: {title}",
                    link=link, summary=" | ".join(summary_parts),
                    source="Semantic Scholar",
                    category=item.get("category", "semantic_scholar"),
                    published_at=iso_or_empty(dt),
                    kind="semantic_scholar",
                    trust_score=int(item.get("trust_score", 8)),
                    extra={
                        "citation_count": citation_count,
                        "influential_citations": influential,
                        "has_pdf": bool(pdf_link),
                    },
                ))
            time.sleep(1.0)  # S2 API rate limit
        except Exception as exc:
            print(f"[WARN] Semantic Scholar failed ({item.get('query')}): {exc}", file=sys.stderr)

    return articles


# ---------------------------------------------------------------------------
# Scoring & deduplication
# ---------------------------------------------------------------------------

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

    title_lower = article.title.lower()
    for keyword, weight in KEYWORD_WEIGHTS.items():
        if keyword.lower() in title_lower:
            score += min(weight, 12)

    # Kind-specific bonus
    if article.kind == "arxiv":
        score += 8
    elif article.kind == "hf_paper":
        score += 10
        upvotes = article.extra.get("upvotes", 0) or 0
        score += min(upvotes // 5, 15)
    elif article.kind == "hf_model":
        downloads = article.extra.get("downloads", 0) or 0
        likes = article.extra.get("likes", 0) or 0
        score += min(downloads // 50000, 10) + min(likes // 100, 8)
        if article.extra.get("relevant_tags"):
            score += 8
    elif article.kind == "github_release":
        score += 12  # Release'ler her zaman önemli
    elif article.kind == "github_trending":
        stars_today = article.extra.get("stars_today", 0) or 0
        score += min(stars_today // 50, 12)
    elif article.kind == "papers_with_code":
        score += 7
        if article.extra.get("has_code"):
            score += 5
        repo_stars = article.extra.get("repo_stars", 0) or 0
        score += min(repo_stars // 500, 8)
    elif article.kind == "semantic_scholar":
        influential = article.extra.get("influential_citations", 0) or 0
        score += min(influential // 2, 12)

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
        tk_short = " ".join(tk.split()[:14])
        if uk in seen_urls or tk_short in seen_titles:
            continue
        seen_urls.add(uk)
        seen_titles.add(tk_short)
        unique.append(article)
    return unique


# ---------------------------------------------------------------------------
# Collect
# ---------------------------------------------------------------------------

def collect_articles() -> List[Article]:
    sources = load_sources()
    articles: List[Article] = []

    print("[INFO] Fetching RSS sources...", file=sys.stderr)
    articles.extend(fetch_rss_sources(sources.get("rss_sources", [])))

    print("[INFO] Fetching Google News...", file=sys.stderr)
    articles.extend(fetch_google_news(sources.get("google_news_queries", [])))

    print("[INFO] Fetching arXiv...", file=sys.stderr)
    articles.extend(fetch_arxiv(sources.get("arxiv_queries", [])))

    print("[INFO] Fetching HuggingFace trending models...", file=sys.stderr)
    articles.extend(fetch_hf_trending_models())

    print("[INFO] Fetching HuggingFace daily papers...", file=sys.stderr)
    articles.extend(fetch_hf_daily_papers())

    print("[INFO] Fetching GitHub releases...", file=sys.stderr)
    articles.extend(fetch_github_releases())

    print("[INFO] Fetching GitHub trending...", file=sys.stderr)
    articles.extend(fetch_github_trending())

    if ENABLE_PWC:
        print("[INFO] Fetching Papers With Code...", file=sys.stderr)
        articles.extend(fetch_papers_with_code(PWC_TASKS))
    else:
        print("[INFO] Papers With Code disabled by default. Set ENABLE_PWC=true to enable.", file=sys.stderr)

    print("[INFO] Fetching Semantic Scholar...", file=sys.stderr)
    articles.extend(fetch_semantic_scholar(sources.get("semantic_scholar_queries", [])))

    print(f"[INFO] Raw total: {len(articles)}", file=sys.stderr)
    articles = deduplicate(articles)
    articles = [score_article(a) for a in articles]
    articles.sort(key=lambda a: a.score, reverse=True)
    final = articles[:MAX_CANDIDATES]
    print(f"[INFO] After dedup+score: {len(final)}", file=sys.stderr)
    return final


# ---------------------------------------------------------------------------
# Prompt & generation
# ---------------------------------------------------------------------------

def build_prompt(articles: List[Article]) -> str:
    now_tr = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
    data = [a.to_prompt_dict() for a in articles]
    mode_label = "haftalık derin trend raporu" if BULLETIN_MODE == "weekly" else "günlük teknoloji istihbarat bülteni"

    # Kaynak dağılımını özetle
    kind_counts: Dict[str, int] = {}
    for a in articles:
        kind_counts[a.kind] = kind_counts.get(a.kind, 0) + 1

    kind_summary = ", ".join(f"{k}:{v}" for k, v in sorted(kind_counts.items(), key=lambda x: -x[1]))

    if BULLETIN_MODE == "weekly":
        task = f"""
Bu haber/makale listesinden haftalık bir AI + savunma sanayi + robotik + UAV + edge AI trend raporu üret.

Rapor yapısı:
1. Yönetici özeti: 5-6 madde.
2. Bu haftanın ana trendleri: 6 başlık.
3. Kategori bazlı analiz:
   - Savunma AI / Military AI
   - UAV / Drone / Counter-UAS
   - Robotik / Humanoid / Embodied AI
   - Computer Vision / Edge AI
   - HuggingFace model & paper sinyalleri
   - GitHub release & trending sinyalleri
   - Papers With Code SOTA kırılmaları
   - Akademik (arXiv + Semantic Scholar) sinyalleri
   - Türkiye savunma sanayi notları
4. En önemli {BULLETIN_ITEMS} gelişme:
   Her biri için başlık, kaynak türü, 2-3 cümle özet, stratejik önem, teknik çıkarım, link.
5. Rabia'nın İHA / computer vision / edge AI / OnkoNixAI açısından takip notları.
6. Gelecek hafta izlenecek anahtar kelimeler ve repolar.
"""
    else:
        task = f"""
Bu haber/makale listesinden Türkçe {mode_label} üret.

Bülten yapısı:
- Başlık: 🤖 Günlük AI + Savunma + Robotik Bülteni — {now_tr}
- Önce 5-6 maddelik kısa radar özeti ver.
- Sonra en önemli {BULLETIN_ITEMS} gelişmeyi kategori bazlı sırala.
- Her gelişme için:
  1) Başlık
  2) Kaynak türü (haber / arXiv / HF model / HF paper / GitHub release / GitHub trend / Papers With Code / Semantic Scholar)
  3) Kısa özet: 2-3 cümle
  4) Neden önemli?
  5) İHA / robotik / savunma / edge AI açısından teknik çıkarım
  6) Kaynak linki
- HuggingFace model trendlerini "Model Sinyali" olarak işaretle; downloads ve likes sayısını belirt.
- GitHub release'leri "Kritik Güncelleme" olarak öne çıkar.
- Papers With Code girişlerini "SOTA Kırılması" olarak belirt; koda erişim olup olmadığını yaz.
- Semantic Scholar girişlerini "Etkili Makale" olarak belirt; citation sayısını yaz.
- Akademik arXiv girdilerini "Araştırma Sinyali" olarak belirt.
- En sona "Bugünün stratejik trend yorumu" ve "Takip edilmesi gereken repolar" ekle.
"""

    return f"""
Sen Rabia için çalışan teknik bir AI mühendislik haber analisti gibi davranıyorsun.
Rabia'nın ilgi alanları: savunma sanayi, UAV/İHA, computer vision, edge AI, robotik, sürü robotik, autonomous systems, counter-UAS, NVIDIA Jetson/Hailo, YOLO/object tracking, medikal AI ve OnkoNixAI.

Bugünkü veri kaynakları: {kind_summary}
Toplam aday: {len(articles)} öğe

Kurallar:
- Türkçe yaz.
- Teknik ama okunabilir ol.
- Abartılı pazarlama dili kullanma.
- HuggingFace modellerini açıklarken pipeline task'ı, download sayısı ve ilgili tagları belirt.
- GitHub release'lerde versiyon numarasını ve öne çıkan değişikliği söyle.
- Papers With Code'da SOTA kırılan benchmark ve dataset adını belirt.
- Semantic Scholar'da citation count ve influential citation'ı yaz.
- Aynı konuyu tekrar etme.
- Linkleri mutlaka koru.
- Telegram mesajı için sade metin üret; Markdown tablo kullanma.
- Çok uzun yazma; yoğun ama okunabilir olsun.

{task}

Aday haberler ve makaleler JSON:
{json.dumps(data, ensure_ascii=False, indent=2)}
""".strip()


def is_retryable_gemini_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in ["503", "unavailable", "high demand", "429", "resource_exhausted", "rate limit"])


def candidate_gemini_models() -> List[str]:
    models: List[str] = []
    for model in [GEMINI_MODEL] + GEMINI_FALLBACK_MODELS:
        if model and model not in models:
            models.append(model)
    return models


def generate_bulletin(articles: List[Article]) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY eksik. GitHub Secrets içine ekleyin.")

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = build_prompt(articles)
    last_error: Optional[Exception] = None

    for model in candidate_gemini_models():
        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            try:
                print(f"[INFO] Gemini generate: model={model}, attempt={attempt}", file=sys.stderr)
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                )
                text = getattr(response, "text", None) or str(response)
                text = text.replace("\\n", "\n")
                return clean_text_preserve_lines(text)
            except Exception as exc:
                last_error = exc
                if not is_retryable_gemini_error(exc) or attempt >= GEMINI_MAX_RETRIES:
                    print(f"[WARN] Gemini failed: model={model}, attempt={attempt}, error={exc}", file=sys.stderr)
                    break
                sleep_seconds = min(45, 8 * attempt)
                print(f"[WARN] Gemini temporary error. Retrying in {sleep_seconds}s: {exc}", file=sys.stderr)
                time.sleep(sleep_seconds)

    raise RuntimeError(f"Gemini summary failed after model fallbacks: {last_error}")

def send_telegram_message(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik.")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    chunks = split_message(message, 3900)
    for chunk in chunks:
        response = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "disable_web_page_preview": True},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        time.sleep(0.5)


def split_message(message: str, max_len: int) -> List[str]:
    if len(message) <= max_len:
        return [message]
    chunks = []
    current = ""
    for paragraph in message.split("\n"):
        if len(current) + len(paragraph) + 1 <= max_len:
            current += ("\n" if current else "") + paragraph
        else:
            if current:
                chunks.append(current)
            while len(paragraph) > max_len:
                chunks.append(paragraph[:max_len])
                paragraph = paragraph[max_len:]
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def fallback_bulletin(articles: List[Article]) -> str:
    now_tr = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
    lines = [f"🤖 AI + Savunma + Robotik Bülteni — {now_tr}", "", "Gemini özetleme çalışmadı; ham aday listesi.", ""]
    for idx, article in enumerate(articles[:BULLETIN_ITEMS], 1):
        lines.extend([
            f"{idx}) [{article.kind.upper()}] {article.title}",
            f"Kategori: {CATEGORY_LABELS.get(article.category, article.category)}",
            f"Skor: {round(article.score, 1)} | Kaynak: {article.source}",
            f"Özet: {shorten(article.summary, 260)}",
            f"Link: {article.link}",
            "",
        ])
    return "\n".join(lines)


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