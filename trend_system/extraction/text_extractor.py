from __future__ import annotations
import re
import hashlib
from datetime import datetime, timezone

import dateparser
from langdetect import detect, DetectorFactory

DetectorFactory.seed = 0

def clean_with_trafilatura(html: str) -> str:
    try:
        from trafilatura import extract
        text = extract(html, include_comments=False, include_tables=False)
        if text:
            return text
    except Exception:
        pass
    # fallback: strip tags
    return re.sub(r"<[^>]+>", " ", html)

def detect_language(text: str) -> str:
    try:
        lang = detect(text[:1000])
        if lang.startswith("fa"):
            return "fa"
        return lang
    except Exception:
        # heuristic Persian detection
        if re.search(r"[\u0600-\u06FF]", text):
            return "fa"
        return "en"

def parse_date(date_str: str | None, fallback: datetime | None = None) -> datetime | None:
    if not date_str:
        return fallback
    # try dateparser with fa support
    try:
        dt = dateparser.parse(date_str, languages=["fa","en"])
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    except Exception:
        pass
    return fallback

def extract_metadata(html: str, url: str) -> dict:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    title = None
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"]
    # publication date
    pub = None
    for sel in [
        'meta[property="article:published_time"]',
        'meta[name="pubdate"]',
        'meta[name="publishdate"]',
        'meta[name="date"]',
        'time[datetime]',
    ]:
        el = soup.select_one(sel)
        if el:
            val = el.get("content") or el.get("datetime") or el.get_text()
            if val:
                pub = val.strip()
                break
    author=None
    auth_el = soup.find("meta", attrs={"name":"author"}) or soup.find("meta", property="article:author")
    if auth_el:
        author = auth_el.get("content")
    image_urls=[]
    for img in soup.find_all("img", src=True)[:10]:
        src=img["src"]
        if src.startswith("http"):
            image_urls.append(src)
    return {"title": title, "pub_raw": pub, "author": author, "image_urls": image_urls}

def content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

def extract_clean_text(html: str, url: str) -> dict:
    text = clean_with_trafilatura(html)
    text = re.sub(r"\s+", " ", text).strip()
    meta = extract_metadata(html, url)
    lang = detect_language(text[:2000])
    h = content_hash(text)
    parsed_pub = parse_date(meta.get("pub_raw"))
    return {
        "title": meta.get("title"),
        "content_text": text,
        "content_hash": h,
        "language": lang,
        "author": meta.get("author"),
        "image_urls": meta.get("image_urls", []),
        "pub_raw": meta.get("pub_raw"),
        "parsed_pub": parsed_pub,
    }
