import logging
import re
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import List
import xml.etree.ElementTree as ET

import requests


logger = logging.getLogger(__name__)

NEWS_FEED_URL = "https://coinjournal.net/news/feed/"
NEWS_FEED_CACHE_TTL_SECONDS = 15 * 60
NEWS_FEED_STALE_TTL_SECONDS = 6 * 60 * 60
NEWS_FEED_WARNING_INTERVAL_SECONDS = 10 * 60

_cached_news_text = ""
_cached_news_at = 0.0
_last_warning_at = 0.0


def _warn_fetch_failure(message: str, *args) -> None:
    global _last_warning_at
    now = time.monotonic()
    if now - _last_warning_at < NEWS_FEED_WARNING_INTERVAL_SECONDS:
        logger.info(message, *args)
        return
    _last_warning_at = now
    logger.warning(message, *args)


def _cached_news_if_available(*, allow_stale: bool = False) -> str:
    if not _cached_news_text:
        return ""
    age = time.monotonic() - _cached_news_at
    ttl = NEWS_FEED_STALE_TTL_SECONDS if allow_stale else NEWS_FEED_CACHE_TTL_SECONDS
    if age <= ttl:
        return _cached_news_text
    return ""


def _strip_html_tags(text: str) -> str:
    if not text:
        return ""
    cleaned = unescape(text)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def fetch_latest_news(max_chars: int = 4000) -> str:
    global _cached_news_at, _cached_news_text

    cached = _cached_news_if_available()
    if cached:
        return cached[:max_chars]

    try:
        response = requests.get(NEWS_FEED_URL, timeout=10)
        if response.status_code != 200:
            _warn_fetch_failure("Failed to fetch news feed: status %s", response.status_code)
            return _cached_news_if_available(allow_stale=True)[:max_chars]

        root = ET.fromstring(response.content)
        channel = root.find("channel")
        if channel is None:
            return ""

        entries: List[str] = []

        for item in channel.findall("item"):
            title = _strip_html_tags(item.findtext("title") or "")
            pub_date_raw = (item.findtext("pubDate") or "").strip()
            summary_raw = item.findtext("description") or ""

            summary = _strip_html_tags(summary_raw)
            summary = re.sub(r"The post .*? appeared first on .*", "", summary, flags=re.IGNORECASE).strip()

            formatted_time = pub_date_raw
            if pub_date_raw:
                try:
                    parsed = parsedate_to_datetime(pub_date_raw)
                    if parsed is not None:
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        else:
                            parsed = parsed.astimezone(timezone.utc)
                        formatted_time = parsed.strftime("%Y-%m-%d %H:%M:%SZ")
                except Exception:  # noqa: BLE001
                    formatted_time = pub_date_raw

            parts = []
            if formatted_time:
                parts.append(formatted_time)
            if title:
                parts.append(title)

            entry_text = " | ".join(parts)
            if summary:
                entry_text = f"{entry_text}: {summary}" if entry_text else summary

            entry_text = entry_text.strip()
            if not entry_text:
                continue

            existing_text = "\n".join(entries)
            candidate_text = f"{existing_text}\n{entry_text}" if existing_text else entry_text
            if len(candidate_text) > max_chars:
                remaining = max_chars - len(existing_text)
                if existing_text:
                    remaining -= 1
                if remaining <= 0:
                    break
                truncated = entry_text[:remaining].rstrip()
                if truncated:
                    if len(truncated) < len(entry_text):
                        truncated = truncated.rstrip(" .,;:-") + "..."
                    entries.append(truncated)
                break

            entries.append(entry_text)

        result = "\n".join(entries)
        if result:
            _cached_news_text = result
            _cached_news_at = time.monotonic()
        return result

    except Exception as err:  # noqa: BLE001
        _warn_fetch_failure("Failed to process news feed: %s", err)
        return _cached_news_if_available(allow_stale=True)[:max_chars]
