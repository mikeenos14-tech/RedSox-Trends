from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree

import httpx

RSS_URL = "https://news.google.com/rss/search"


async def get_recent_headlines(query: str = "Red Sox", days: int = 3, limit: int = 12) -> list[dict]:
    """Fetch recent news headlines via Google News RSS (no API key required)."""
    params = {
        # Exclude MLB.com's auto-generated "on this day" historical Gameday
        # recaps, which otherwise pollute results with 1900s box scores.
        "q": f'"{query}" when:{days}d -"Final Score" -intitle:Gameday',
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(RSS_URL, params=params)
        resp.raise_for_status()
        xml_text = resp.text

    root = ElementTree.fromstring(xml_text)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    headlines = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date_raw = item.findtext("pubDate")
        source_el = item.find("source")
        source = source_el.text.strip() if source_el is not None and source_el.text else None

        if not title or not link:
            continue

        # Google News suffixes the title with " - <source>"; strip it since
        # we already have the source separately.
        if source and title.endswith(f" - {source}"):
            title = title[: -(len(source) + 3)].strip()

        published = None
        if pub_date_raw:
            try:
                dt = parsedate_to_datetime(pub_date_raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
                published = dt.isoformat()
            except (TypeError, ValueError):
                pass

        headlines.append(
            {
                "title": title,
                "link": link,
                "source": source,
                "published": published,
            }
        )

        if len(headlines) >= limit:
            break

    return headlines
