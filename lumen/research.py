from urllib.parse import urlsplit

import httpx

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


class ResearchError(Exception):
    pass


async def search(query: str, api_key: str) -> list[dict]:
    if not api_key:
        raise ResearchError("Save your Brave Search API key in Settings first.")
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=30, follow_redirects=False) as client:
            response = await client.get(
                BRAVE_URL,
                params={"q": query, "count": 6, "safesearch": "moderate"},
                headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            )
            response.raise_for_status()
            results = response.json().get("web", {}).get("results", [])
            sources = []
            for item in results:
                url = item["url"]
                parsed = urlsplit(url)
                if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                    continue
                if parsed.username or parsed.password:
                    continue
                sources.append(
                    {
                        "citation": f"W{len(sources) + 1}",
                        "title": item["title"][:500],
                        "url": url,
                        "text": item.get("description", "")[:3000],
                    }
                )
            if not sources:
                raise ResearchError("Brave returned no usable sources. Narrow or revise the query.")
            return sources
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise ResearchError(
            "Brave search failed or timed out. The approved query may have reached Brave; "
            "no automatic retry was made. Check your API key, quota, and connection."
        ) from exc
