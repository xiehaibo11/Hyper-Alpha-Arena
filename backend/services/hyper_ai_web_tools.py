"""Web lookup tools used by Hyper AI."""

import json
import logging
import re

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def execute_web_search(db: Session, query: str, max_results: int = 5) -> str:
    """Search the web using Tavily API. Returns error with setup guide if key not configured."""
    from services.hyper_ai_tool_registry import get_tool_api_key

    api_key = get_tool_api_key(db, "tavily")
    if not api_key:
        return json.dumps({
            "error": "Web search is not configured. The user needs to set up their Tavily API key.",
            "setup_guide": "Go to Hyper AI page → right panel → Tools section → click Tavily Web Search → enter API key.",
            "get_url": "https://tavily.com",
        })

    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        max_results = min(max(1, max_results), 10)
        response = client.search(query, max_results=max_results)

        results = []
        for result in response.get("results", []):
            results.append({
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "content": result.get("content", "")[:500],
            })

        return json.dumps({
            "query": query,
            "results": results,
            "result_count": len(results),
        })

    except Exception as exc:
        err = str(exc)
        if "401" in err or "Unauthorized" in err:
            return json.dumps({"error": "Tavily API key is invalid or expired. Please update it in Tools settings."})
        logger.error("[web_search] Error: %s", exc)
        return json.dumps({"error": f"Search failed: {err}"})


def execute_fetch_url(url: str, max_length: int = 8000) -> str:
    """Fetch URL content using Jina Reader API with trafilatura fallback."""
    import requests as req

    max_length = min(max(1000, max_length), 15000)

    if not url or not url.startswith(("http://", "https://")):
        return json.dumps({"error": "Invalid URL. Must start with http:// or https://"})

    content = None
    source = None

    try:
        jina_url = f"https://r.jina.ai/{url}"
        headers = {
            "Accept": "text/plain",
            "X-No-Cache": "true",
        }
        resp = req.get(jina_url, headers=headers, timeout=30)
        if resp.status_code == 200 and len(resp.text.strip()) > 100:
            content = resp.text.strip()
            source = "jina_reader"
    except Exception as exc:
        logger.warning("[fetch_url] Jina Reader failed for %s: %s", url, exc)

    if not content:
        try:
            import trafilatura

            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                extracted = trafilatura.extract(
                    downloaded,
                    output_format="txt",
                    include_links=True,
                    include_tables=True,
                )
                if extracted and len(extracted.strip()) > 50:
                    content = extracted.strip()
                    source = "trafilatura"
        except Exception as exc:
            logger.warning("[fetch_url] Trafilatura failed for %s: %s", url, exc)

    if not content:
        try:
            resp = req.get(url, timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (compatible; HyperAI/1.0)",
            })
            if resp.status_code == 200:
                text = resp.text
                text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
                text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
                text = re.sub(r'<[^>]+>', ' ', text)
                text = re.sub(r'\s+', ' ', text).strip()
                if len(text) > 50:
                    content = text
                    source = "raw_requests"
        except Exception as exc:
            logger.warning("[fetch_url] Raw fetch failed for %s: %s", url, exc)

    if not content:
        return json.dumps({"error": f"Failed to fetch content from {url}. The page may be inaccessible or require authentication."})

    truncated = len(content) > max_length
    if truncated:
        content = content[:max_length] + "\n\n[Content truncated...]"

    return json.dumps({
        "url": url,
        "content": content,
        "content_length": len(content),
        "truncated": truncated,
        "source": source,
    })
