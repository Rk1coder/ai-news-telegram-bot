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
WEEKLY_GEMINI_MODEL = os.getenv("WEEKLY_GEMINI_MODEL", "gemini-2.5-pro").strip() or "gemini-2.5-pro"
GEMINI_FALLBACK_MODELS = [
    m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash-lite,gemini-2.0-flash").split(",") if m.strip()
]
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "3"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_DISABLE_PREVIEW = os.getenv("TELEGRAM_DISABLE_PREVIEW", "true").lower() == "true"

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
HF_TOKEN = os.getenv("HF_TOKEN", "").strip()
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()

BULLETIN_MODE = os.getenv("BULLETIN_MODE", "daily").strip().lower()
MAX_AGE_HOURS = int(os.getenv("MAX_AGE_HOURS", "48"))
MAX_CANDIDATES = int(os.getenv("MAX_CANDIDATES", "35"))
BULLETIN_ITEMS = int(os.getenv("BULLETIN_ITEMS", "7"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
ARXIV_MAX_QUERIES = int(os.getenv("ARXIV_MAX_QUERIES", "4"))
SEMANTIC_SCHOLAR_MAX_QUERIES = int(os.getenv("SEMANTIC_SCHOLAR_MAX_QUERIES", "2"))
ENABLE_HF_TRENDING = os.getenv("ENABLE_HF_TRENDING", "false").lower() == "true"
ENABLE_GITHUB_TRENDING = os.getenv("ENABLE_GITHUB_TRENDING", "true").lower() == "true"
ENABLE_SEMANTIC_SCHOLAR = os.getenv("ENABLE_SEMANTIC_SCHOLAR", "false").lower() == "true"

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
    "hf_model": "HuggingFace: Yeni Model",
    "hf_paper": "HuggingFace: Günün Makalesi",
    "github_trending": "GitHub: Trend Repo",
    "github_release": "GitHub: Kritik Release",
    "papers_with_code": "Papers With Code: SOTA",
    "semantic_scholar": "Semantic Scholar: Etkili Makale",
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
    "military ai": 18, "defense ai": 18, "defence ai": 18,
    "autonomous systems": 16, "autonomous system": 14,
    "darpa": 16, "nato": 11,
    "counter-uas": 20, "counter uas": 20,
    "anti-drone": 18, "drone defense": 18, "drone defence": 18,
    "electronic warfare": 15, "sensor fusion": 13,
    "target tracking": 13, "surveillance": 9,
    "uav": 18, "uas": 14, "drone": 13, "drones": 13,
    "sürü iha": 22, "iha": 18, "siha": 18,
    "baykar": 18, "aselsan": 18, "tusaş": 17, "tusas": 17,
    "stm": 12, "havelsan": 15, "roketsan": 13,
    "savunma sanayi": 18, "otonom sistem": 16,
    "robotics": 15, "robotic": 12, "humanoid": 18,
    "embodied ai": 17, "robot foundation model": 17,
    "legged robot": 14, "quadruped": 13, "manipulation": 11,
    "computer vision": 15, "object detection": 14,
    "object tracking": 14, "visual tracking": 13,
    "real-time detection": 14, "yolo": 16,
    "jetson": 15, "edge ai": 16, "on-device": 13,
    "inference": 8, "hailo": 14, "multimodal": 10,
    "onnx": 10, "tensorrt": 12, "openvino": 10,
    "ai agent": 12, "ai agents": 12,
    "multi-agent": 15, "swarm": 18,
    "reinforcement learning": 11, "foundation model": 10,
    "vision-language": 11, "vla": 10,
    "diffusion": 9, "transformer": 8,
    "fine-tuned": 10, "quantized": 12, "gguf": 11,
    "lora": 10, "peft": 9, "benchmark": 8,
    "open source": 7, "open-source": 7,
    "release": 8, "real-time": 12, "deployment": 9,
    "arxiv": 9, "paper": 7, "dataset": 8,
    "state-of-the-art": 14, "sota": 14,
}

NOISE_PATTERNS = [
    r"\bcrypto\b", r"\bstock market\b", r"\bcelebrity\b",
    r"\bhoroscope\b", r"\bgambling\b",
]

GITHUB_WATCH_REPOS = [
    {"owner": "ultralytics", "repo": "ultralytics", "category": "edge_ai", "trust_score": 9},
    {"owner": "ultralytics", "repo": "yolov5", "category": "edge_ai", "trust_score": 8},
    {"owner": "hailo-ai", "repo": "hailo-rpi5-examples", "category": "edge_ai", "trust_score": 8},
    {"owner": "NVIDIA", "repo": "TensorRT-LLM", "category": "edge_ai", "trust_score": 9},
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

HF_RELEVANT_TAGS = {
    "object-detection", "image-classification", "image-segmentation",
    "video-classification", "depth-estimation", "keypoint-detection",
    "robotics", "reinforcement-learning", "text-to-image",
    "visual-question-answering", "zero-shot-object-detection",
    "autonomous-driving",
}

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
        return {
            "title": self.title,
            "source": self.source,
            "category": CATEGORY_LABELS.get(self.category, self.category),
            "published_at": self.published_at,
            "score": round(self.score, 2),
            "matched_keywords": self.matched_keywords[:8],
            "summary": shorten(clean_text(self.summary), 520),
            "link": self.link,
            "kind": self.kind,
            "extra": self.extra,
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
    return dt.astimezone(timezone.utc).isoformat() if dt else ""


def is_recent(dt: Optional[datetime], max_age_hours: int) -> bool:
    if not dt:
        return True
    return dt >= datetime.now(timezone.utc) - timedelta(hours=max_age_hours)


def load_sources() -> Dict[str, Any]:
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_url(url: str, headers: Optional[Dict[str, str]] = None) -> bytes:
    _headers = {
        "User-Agent": "Mozilla/5.0 AI-Intel-Telegram-Bot/3.0",
        "Accept": "application/rss+xml, application/atom+xml, application/json, text/html, */*",
    }
    if headers:
        _headers.update(headers)
    response = requests.get(url, headers=_headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.content


def fetch_json(url: str, headers: Optional[Dict[str, str]] = None) -> Any:
    _headers = {"User-Agent": "Mozilla/5.0 AI-Intel-Telegram-Bot/3.0", "Accept": "application/json"}
    if headers:
        _headers.update(headers)
    response = requests.get(url, headers=_headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    return feedparser.parse(fetch_url(url))


def entry_datetime(entry: feedparser.FeedParserDict) -> Optional[datetime]:
    for key in ["published", "updated", "created", "pubDate", "date"]:
        dt = parse_datetime(entry.get(key))
        if dt:
            return dt
    return None


def github_headers() -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def hf_headers() -> Dict[str, str]:
    h = {"Accept": "application/json"}
    if HF_TOKEN:
        h["Authorization"] = f"Bearer {HF_TOKEN}"
    return h


def fetch_rss_sources(sources: List[Dict[str, Any]]) -> List[Article]:
    articles: List[Article] = []
    for src in sources:
        try:
            parsed = fetch_feed(src["url"])
            for entry in parsed.entries[:20]:
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
                summary = clean_text(entry.get("summary", "") or entry.get("description", "") or content_value)
                if title and link:
                    articles.append(Article(
                        title=title, link=link, summary=summary,
                        source=src.get("name", "RSS"), category=src.get("category", "general_ai"),
                        published_at=iso_or_empty(dt), kind="rss", trust_score=int(src.get("trust_score", 5)),
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
    for item in queries:
        try:
            parsed = fetch_feed(google_news_url(item["query"], item.get("language", "en"), item.get("region", "US"), MAX_AGE_HOURS))
            for entry in parsed.entries[:12]:
                dt = entry_datetime(entry)
                if not is_recent(dt, MAX_AGE_HOURS):
                    continue
                title = clean_text(entry.get("title", ""))
                link = clean_text(entry.get("link", ""))
                summary = clean_text(entry.get("summary", "") or entry.get("description", ""))
                source = "Google News"
                if isinstance(entry.get("source"), dict):
                    source = clean_text(entry.get("source", {}).get("title", "")) or source
                if title and link:
                    articles.append(Article(
                        title=title, link=link, summary=summary, source=source,
                        category=item.get("category", "general_ai"), published_at=iso_or_empty(dt),
                        kind="google_news", trust_score=int(item.get("trust_score", 5)),
                    ))
        except Exception as exc:
            print(f"[WARN] Google News fetch failed: {item.get('query')} - {exc}", file=sys.stderr)
    return articles


def fetch_arxiv(queries: List[Dict[str, Any]]) -> List[Article]:
    articles: List[Article] = []
    for item in queries[:ARXIV_MAX_QUERIES]:
        for attempt in range(2):
            try:
                search_query = urllib.parse.quote(item["query"])
                url = (
                    "https://export.arxiv.org/api/query?"
                    f"search_query={search_query}&start=0&max_results=6"
                    "&sortBy=submittedDate&sortOrder=descending"
                )
                parsed = fetch_feed(url)
                for entry in parsed.entries[:6]:
                    dt = entry_datetime(entry)
                    if not is_recent(dt, MAX_AGE_HOURS * 3):
                        continue
                    title = clean_text(entry.get("title", ""))
                    link = clean_text(entry.get("link", ""))
                    summary = clean_text(entry.get("summary", ""))
                    if title and link:
                        articles.append(Article(
                            title=title, link=link, summary=summary, source="arXiv",
                            category=item.get("category", "research"), published_at=iso_or_empty(dt),
                            kind="arxiv", trust_score=int(item.get("trust_score", 8)),
                        ))
                break
            except Exception as exc:
                print(f"[WARN] arXiv fetch failed: {item.get('query')} - {exc}", file=sys.stderr)
                time.sleep(4 + attempt * 4)
        time.sleep(3)
    return articles


def fetch_hf_daily_papers() -> List[Article]:
    articles: List[Article] = []
    try:
        data = fetch_json("https://huggingface.co/api/daily_papers?limit=15", headers=hf_headers())
        papers = data if isinstance(data, list) else []
        for paper in papers[:15]:
            paper_info = paper.get("paper") or paper
            arxiv_id = paper_info.get("id", "") or paper_info.get("arxivId", "")
            title = clean_text(paper_info.get("title", ""))
            if not title:
                continue
            summary = clean_text(paper_info.get("summary", "") or paper_info.get("abstract", ""))
            dt = parse_datetime(paper.get("publishedAt") or paper_info.get("publishedAt", ""))
            if not is_recent(dt, MAX_AGE_HOURS * 3):
                continue
            link = f"https://huggingface.co/papers/{arxiv_id}" if arxiv_id else "https://huggingface.co/papers"
            authors = [a.get("name", "") for a in (paper_info.get("authors") or [])[:3]]
            articles.append(Article(
                title=f"HF Paper: {title}", link=link, summary=summary, source="HuggingFace Papers",
                category="hf_paper", published_at=iso_or_empty(dt), kind="hf_paper", trust_score=9,
                extra={"arxiv_id": arxiv_id, "authors": authors},
            ))
    except Exception as exc:
        print(f"[WARN] HuggingFace daily papers failed: {exc}", file=sys.stderr)
    return articles


def fetch_hf_trending_models() -> List[Article]:
    if not ENABLE_HF_TRENDING:
        return []
    articles: List[Article] = []
    try:
        data = fetch_json("https://huggingface.co/api/trending-repos?limit=20&type=model", headers=hf_headers())
        repos = data if isinstance(data, list) else data.get("recentlyTrending", [])
        now = datetime.now(timezone.utc)
        for repo in repos[:20]:
            repo_data = repo.get("repoData") or repo
            repo_id = repo.get("id") or repo_data.get("id") or ""
            if not repo_id:
                continue
            pipeline_tag = repo_data.get("pipeline_tag", "") or ""
            tags = list(repo_data.get("tags") or [])
            if pipeline_tag:
                tags.append(pipeline_tag)
            relevant = HF_RELEVANT_TAGS.intersection(set(t.lower() for t in tags))
            downloads = repo_data.get("downloads", 0) or 0
            likes = repo_data.get("likes", 0) or 0
            if not relevant and downloads < 5000:
                continue
            articles.append(Article(
                title=f"HF Model Trend: {repo_id}", link=f"https://huggingface.co/{repo_id}",
                summary=f"Task: {pipeline_tag} | Tags: {', '.join(tags[:6])} | Downloads: {downloads:,} | Likes: {likes:,}",
                source="HuggingFace Trending", category="hf_model", published_at=iso_or_empty(now),
                kind="hf_model", trust_score=8,
                extra={"downloads": downloads, "likes": likes, "pipeline_tag": pipeline_tag, "relevant_tags": list(relevant)},
            ))
    except Exception as exc:
        print(f"[WARN] HuggingFace trending models failed: {exc}", file=sys.stderr)
    return articles


def fetch_github_releases() -> List[Article]:
    articles: List[Article] = []
    headers = github_headers()
    for repo_info in GITHUB_WATCH_REPOS:
        owner, repo = repo_info["owner"], repo_info["repo"]
        try:
            releases = fetch_json(f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=2", headers=headers)
            if not isinstance(releases, list):
                continue
            for release in releases[:2]:
                if release.get("prerelease"):
                    continue
                dt = parse_datetime(release.get("published_at") or release.get("created_at", ""))
                if not is_recent(dt, MAX_AGE_HOURS * 4):
                    continue
                tag = release.get("tag_name", "")
                body = clean_text(release.get("body", ""))
                articles.append(Article(
                    title=f"Release: {owner}/{repo} {tag}",
                    link=release.get("html_url", f"https://github.com/{owner}/{repo}/releases"),
                    summary=shorten(body, 420) if body else f"{owner}/{repo} için {tag} sürümü yayınlandı.",
                    source=f"GitHub: {owner}/{repo}", category=repo_info.get("category", "github_release"),
                    published_at=iso_or_empty(dt), kind="github_release", trust_score=int(repo_info.get("trust_score", 8)),
                    extra={"tag": tag, "repo": f"{owner}/{repo}"},
                ))
            time.sleep(0.25)
        except Exception as exc:
            print(f"[WARN] GitHub release fetch failed: {owner}/{repo} - {exc}", file=sys.stderr)
    return articles


def fetch_github_trending() -> List[Article]:
    if not ENABLE_GITHUB_TRENDING:
        return []
    articles: List[Article] = []
    urls = [("https://github.com/trending/python?since=daily", "Python"), ("https://github.com/trending?since=daily", "All")]
    filter_keywords = {"robot", "drone", "uav", "vision", "detection", "yolo", "ai", "ml", "inference", "edge", "jetson", "tracking", "slam", "autonomous", "rl", "diffusion", "transformer", "segment", "lidar", "3d"}
    now = datetime.now(timezone.utc)
    for url, lang in urls:
        try:
            content = fetch_url(url).decode("utf-8", errors="ignore")
            repo_blocks = re.findall(r'<article[^>]*class="[^"]*Box-row[^"]*"[^>]*>(.*?)</article>', content, re.DOTALL)
            for block in repo_blocks[:15]:
                name_match = re.search(r'href="/([^"]+)"[^>]*>\s*([^<]+)\s*</a>', block)
                if not name_match:
                    continue
                repo_path = name_match.group(1).strip()
                if repo_path.count("/") != 1:
                    continue
                desc_match = re.search(r'<p[^>]*class="[^"]*col-9[^"]*"[^>]*>(.*?)</p>', block, re.DOTALL)
                description = clean_text(desc_match.group(1)) if desc_match else ""
                searchable = f"{repo_path} {description}".lower()
                if not any(kw in searchable for kw in filter_keywords):
                    continue
                stars_today = 0
                today_match = re.search(r'([\d,]+)\s*stars today', block)
                if today_match:
                    stars_today = int(today_match.group(1).replace(",", ""))
                articles.append(Article(
                    title=f"GitHub Trend: {repo_path}", link=f"https://github.com/{repo_path}",
                    summary=f"{description} | +{stars_today} stars today | Lang: {lang}",
                    source="GitHub Trending", category="github_trending", published_at=iso_or_empty(now),
                    kind="github_trending", trust_score=7, extra={"stars_today": stars_today, "language": lang},
                ))
        except Exception as exc:
            print(f"[WARN] GitHub trending fetch failed ({lang}): {exc}", file=sys.stderr)
    return articles


def fetch_semantic_scholar(queries: List[Dict[str, Any]]) -> List[Article]:
    if not ENABLE_SEMANTIC_SCHOLAR:
        return []
    articles: List[Article] = []
    base_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    fields = "title,abstract,year,authors,citationCount,influentialCitationCount,externalIds,publicationDate,openAccessPdf"
    headers = {"User-Agent": "AI-Intel-Telegram-Bot/3.0"}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    for item in queries[:SEMANTIC_SCHOLAR_MAX_QUERIES]:
        try:
            params = {"query": item["query"], "fields": fields, "limit": 5, "sort": "citationCount"}
            if item.get("year_filter"):
                params["year"] = item["year_filter"]
            data = fetch_json(f"{base_url}?{urllib.parse.urlencode(params)}", headers=headers)
            for paper in (data.get("data") or [])[:5]:
                title = clean_text(paper.get("title", ""))
                if not title:
                    continue
                abstract = clean_text(paper.get("abstract", "") or "")
                citation_count = paper.get("citationCount", 0) or 0
                influential = paper.get("influentialCitationCount", 0) or 0
                dt = parse_datetime(paper.get("publicationDate", ""))
                external_ids = paper.get("externalIds") or {}
                arxiv_id = external_ids.get("ArXiv", "")
                doi = external_ids.get("DOI", "")
                link = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else (f"https://doi.org/{doi}" if doi else f"https://www.semanticscholar.org/paper/{paper.get('paperId', '')}")
                authors = [a.get("name", "") for a in (paper.get("authors") or [])[:3]]
                articles.append(Article(
                    title=f"S2: {title}", link=link,
                    summary=f"{abstract[:360]} | Cited by: {citation_count} | Influential: {influential} | Authors: {', '.join(authors)}",
                    source="Semantic Scholar", category=item.get("category", "semantic_scholar"),
                    published_at=iso_or_empty(dt), kind="semantic_scholar", trust_score=int(item.get("trust_score", 8)),
                    extra={"citation_count": citation_count, "influential_citations": influential},
                ))
            time.sleep(2)
        except Exception as exc:
            print(f"[WARN] Semantic Scholar failed ({item.get('query')}): {exc}", file=sys.stderr)
    return articles


def normalized_key(text: str) -> str:
    text = text.lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^a-z0-9ığüşöçİĞÜŞÖÇ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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
    score = CATEGORY_BASE_SCORE.get(article.category, 10) + article.trust_score * 2
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
    if article.kind == "arxiv":
        score += 8
    elif article.kind == "hf_paper":
        score += 10
    elif article.kind == "hf_model":
        downloads = article.extra.get("downloads", 0) or 0
        likes = article.extra.get("likes", 0) or 0
        score += min(downloads // 50000, 10) + min(likes // 100, 8)
        if article.extra.get("relevant_tags"):
            score += 8
    elif article.kind == "github_release":
        score += 12
    elif article.kind == "github_trending":
        score += min((article.extra.get("stars_today", 0) or 0) // 50, 12)
    elif article.kind == "semantic_scholar":
        score += min((article.extra.get("influential_citations", 0) or 0) // 2, 12)
    if looks_noisy(article):
        score -= 30
    article.score = max(score, 0)
    article.matched_keywords = sorted(set(matched))[:10]
    return article


def deduplicate(articles: Iterable[Article]) -> List[Article]:
    seen_urls, seen_titles, unique = set(), set(), []
    for article in articles:
        if not article.title or not article.link:
            continue
        uk = url_key(article.link)
        tk_short = " ".join(normalized_key(article.title).split()[:14])
        if uk in seen_urls or tk_short in seen_titles:
            continue
        seen_urls.add(uk)
        seen_titles.add(tk_short)
        unique.append(article)
    return unique


def collect_articles() -> List[Article]:
    sources = load_sources()
    articles: List[Article] = []
    print("[INFO] Fetching RSS sources...", file=sys.stderr)
    articles.extend(fetch_rss_sources(sources.get("rss_sources", [])))
    print("[INFO] Fetching Google News...", file=sys.stderr)
    articles.extend(fetch_google_news(sources.get("google_news_queries", [])))
    print("[INFO] Fetching arXiv...", file=sys.stderr)
    articles.extend(fetch_arxiv(sources.get("arxiv_queries", [])))
    print("[INFO] Fetching HuggingFace daily papers...", file=sys.stderr)
    articles.extend(fetch_hf_daily_papers())
    print("[INFO] Fetching HuggingFace trending models...", file=sys.stderr)
    articles.extend(fetch_hf_trending_models())
    print("[INFO] Fetching GitHub releases...", file=sys.stderr)
    articles.extend(fetch_github_releases())
    print("[INFO] Fetching GitHub trending...", file=sys.stderr)
    articles.extend(fetch_github_trending())
    print("[INFO] Fetching Semantic Scholar...", file=sys.stderr)
    articles.extend(fetch_semantic_scholar(sources.get("semantic_scholar_queries", [])))
    print(f"[INFO] Raw total: {len(articles)}", file=sys.stderr)
    articles = deduplicate(articles)
    articles = [score_article(a) for a in articles]
    articles.sort(key=lambda a: a.score, reverse=True)
    final = articles[:MAX_CANDIDATES]
    print(f"[INFO] After dedup+score: {len(final)}", file=sys.stderr)
    return final


def build_json_prompt(articles: List[Article]) -> str:
    now_tr = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
    data = [a.to_prompt_dict() for a in articles]
    items = 10 if BULLETIN_MODE == "weekly" else BULLETIN_ITEMS
    return f"""
Sen teknik bir AI + savunma sanayi + robotik haber analistisin.
Kullanıcı Rabia; ilgi alanları: UAV/İHA, savunma sanayi, counter-UAS, computer vision, edge AI, YOLO, Hailo/NVIDIA Jetson, robotik, sürü sistemleri, medikal AI ve OnkoNixAI.

Görev: Aşağıdaki adaylardan Telegram için kısa, düzenli ve teknik Türkçe bülten üret.

ÇIKTI KURALI:
- Sadece geçerli JSON döndür.
- Markdown kullanma.
- **, *, #, tablo, [link](url) kullanma.
- Link alanını aynen JSON field olarak ver.
- Her metin kısa olsun.
- summary en fazla 280 karakter.
- why_important en fazla 240 karakter.
- technical_note en fazla 260 karakter.
- radar maddeleri en fazla 130 karakter.
- trend_commentary en fazla 700 karakter.

JSON ŞEMASI:
{{
  "title": "Günlük AI + Savunma + Robotik Bülteni",
  "date": "{now_tr}",
  "radar": ["madde 1", "madde 2", "madde 3", "madde 4", "madde 5"],
  "items": [
    {{
      "title": "kısa başlık",
      "category": "kategori",
      "source_type": "haber | arXiv | HF paper | HF model | GitHub release | GitHub trend | Semantic Scholar",
      "source": "kaynak adı",
      "score": 0,
      "signal_label": "Kritik Güncelleme | Araştırma Sinyali | Model Sinyali | Saha Sinyali | Stratejik Haber",
      "summary": "2 cümlelik kısa özet",
      "why_important": "neden önemli",
      "technical_note": "İHA / robotik / savunma / edge AI açısından teknik çıkarım",
      "link": "https://..."
    }}
  ],
  "trend_commentary": "bugünün stratejik trend yorumu",
  "watch_repos": ["repo1", "repo2", "repo3"]
}}

Seçilecek item sayısı: {items}
Mod: {BULLETIN_MODE}

Adaylar:
{json.dumps(data, ensure_ascii=False, indent=2)}
""".strip()


def strip_json_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text


def generate_structured_bulletin(articles: List[Article]) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY eksik. GitHub Secrets içine ekleyin.")
    client = genai.Client(api_key=GEMINI_API_KEY)
    primary = WEEKLY_GEMINI_MODEL if BULLETIN_MODE == "weekly" else GEMINI_MODEL
    models = []
    for model in [primary] + GEMINI_FALLBACK_MODELS:
        if model and model not in models:
            models.append(model)
    prompt = build_json_prompt(articles)
    last_error = None
    for model in models:
        for attempt in range(1, GEMINI_MAX_RETRIES + 1):
            try:
                print(f"[INFO] Gemini model={model} attempt={attempt}", file=sys.stderr)
                response = client.models.generate_content(model=model, contents=prompt)
                text = getattr(response, "text", None) or str(response)
                parsed = json.loads(strip_json_fence(text))
                if not isinstance(parsed.get("items"), list):
                    raise ValueError("Gemini JSON içinde items listesi yok.")
                return parsed
            except Exception as exc:
                last_error = exc
                print(f"[WARN] Gemini failed model={model} attempt={attempt}: {exc}", file=sys.stderr)
                time.sleep(min(12, 2 * attempt))
    raise RuntimeError(f"Gemini tüm modellerde başarısız oldu: {last_error}")


def h(value: Any) -> str:
    return html.escape(clean_text(value), quote=True)


def link_html(url: str, label: str) -> str:
    url = clean_text(url)
    if not url:
        return h(label)
    safe_url = html.escape(url, quote=True)
    safe_label = h(label or "Kaynak")
    return f'<a href="{safe_url}">{safe_label}</a>'


def clamp(value: Any, limit: int) -> str:
    return h(shorten(clean_text(value), limit))


def render_bulletin_blocks(data: Dict[str, Any]) -> List[str]:
    now_tr = data.get("date") or datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
    title = h(data.get("title") or "Günlük AI + Savunma + Robotik Bülteni")
    radar = data.get("radar") or []
    items = data.get("items") or []
    blocks: List[str] = []

    header_lines = [
        f"🤖 <b>{title}</b>",
        f"🕘 {h(now_tr)} • {len(items)} seçili gelişme",
        "",
        "⚡ <b>Kısa Radar</b>",
    ]
    for r in radar[:6]:
        header_lines.append(f"• {clamp(r, 150)}")
    blocks.append("\n".join(header_lines).strip())

    for idx, item in enumerate(items[: max(BULLETIN_ITEMS, 10) if BULLETIN_MODE == "weekly" else BULLETIN_ITEMS], 1):
        source_name = clean_text(item.get("source") or "Kaynak")
        score = item.get("score", "")
        signal = item.get("signal_label") or item.get("source_type") or "Gelişme"
        category = item.get("category") or "Genel"
        source_type = item.get("source_type") or "haber"
        block = [
            f"<b>{idx}. {clamp(item.get('title'), 180)}</b>",
            f"🏷️ <b>{h(signal)}</b> • {h(category)}",
            f"📍 Kaynak türü: {h(source_type)}" + (f" • Skor: {h(score)}" if str(score) else ""),
            "",
            f"🧩 <b>Özet</b>\n{clamp(item.get('summary'), 420)}",
            "",
            f"🎯 <b>Neden önemli?</b>\n{clamp(item.get('why_important'), 360)}",
            "",
            f"🛠️ <b>Teknik çıkarım</b>\n{clamp(item.get('technical_note'), 420)}",
            "",
            f"🔗 <b>Kaynak:</b> {link_html(item.get('link', ''), source_name)}",
        ]
        blocks.append("\n".join(block).strip())

    tail_lines = []
    if data.get("trend_commentary"):
        tail_lines.extend(["📌 <b>Stratejik Trend Yorumu</b>", clamp(data.get("trend_commentary"), 900)])
    repos = data.get("watch_repos") or []
    if repos:
        tail_lines.extend(["", "🐙 <b>Takip Edilecek Repolar / Alanlar</b>"])
        for repo in repos[:6]:
            tail_lines.append(f"• {clamp(repo, 110)}")
    if tail_lines:
        blocks.append("\n".join(tail_lines).strip())
    return blocks


def fallback_structured_bulletin(articles: List[Article]) -> Dict[str, Any]:
    now_tr = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime("%d.%m.%Y %H:%M")
    top = articles[:BULLETIN_ITEMS]
    return {
        "title": "Günlük AI + Savunma + Robotik Bülteni",
        "date": now_tr,
        "radar": [
            "Gemini özetleme geçici olarak çalışmadı; en yüksek skorlu adaylar temiz kart formatında listelendi.",
            "Kaynaklar RSS, Google News, arXiv, HuggingFace ve GitHub sinyallerinden derlendi.",
            "Google News linkleri ham görünmemesi için Kaynak bağlantısı olarak gizlendi.",
        ],
        "items": [
            {
                "title": a.title,
                "category": CATEGORY_LABELS.get(a.category, a.category),
                "source_type": a.kind,
                "source": a.source,
                "score": round(a.score, 1),
                "signal_label": "Ham Sinyal",
                "summary": shorten(a.summary, 280),
                "why_important": "Bu başlık skorlamada üst sıraya çıktı; savunma, robotik, UAV veya edge AI gündemiyle ilişkili olabilir.",
                "technical_note": "Detaylı AI analizi üretilemediği için bu kart otomatik skor ve kaynak meta verisine göre oluşturuldu.",
                "link": a.link,
            }
            for a in top
        ],
        "trend_commentary": "Gemini API geçici yoğunluk veya JSON üretim hatası nedeniyle otomatik fallback kullanıldı.",
        "watch_repos": ["ultralytics/ultralytics", "huggingface/transformers", "ggerganov/llama.cpp"],
    }


def send_telegram_blocks(blocks: List[str]) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik.")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for block in blocks:
        # Telegram HTML için güvenli sınır. Kart çok uzarsa kuyruğu kısalt.
        if len(block) > 3900:
            block = block[:3800] + "\n\n…"
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": block,
                "parse_mode": "HTML",
                "disable_web_page_preview": TELEGRAM_DISABLE_PREVIEW,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        time.sleep(0.45)


def main() -> None:
    try:
        articles = collect_articles()
        if not articles:
            send_telegram_blocks(["Bugün AI + savunma + robotik alanında yeni aday haber bulunamadı."])
            return
        try:
            bulletin_data = generate_structured_bulletin(articles)
        except Exception as gemini_error:
            print(f"[WARN] Gemini failed, using structured fallback: {gemini_error}", file=sys.stderr)
            bulletin_data = fallback_structured_bulletin(articles)
        blocks = render_bulletin_blocks(bulletin_data)
        send_telegram_blocks(blocks)
        print(f"Sent bulletin with {len(articles)} candidate items and {len(blocks)} Telegram blocks.")
    except Exception as exc:
        err = "⚠️ AI haber botu hata aldı.\n\n" + shorten(traceback.format_exc(), 3000)
        print(err, file=sys.stderr)
        try:
            if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
                send_telegram_blocks([h(err)])
        finally:
            raise exc


if __name__ == "__main__":
    main()
