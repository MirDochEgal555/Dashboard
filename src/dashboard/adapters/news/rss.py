from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from ...domain.models import Headline
from .base import NewsAdapterError

DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_USER_AGENT = "rpi-dashboard/0.1"


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _iter_children(element: ElementTree.Element, tag_name: str) -> Iterable[ElementTree.Element]:
    for child in list(element):
        if _local_name(child.tag) == tag_name:
            yield child


def _first_child(element: ElementTree.Element, tag_name: str) -> ElementTree.Element | None:
    return next(_iter_children(element, tag_name), None)


def _child_text(element: ElementTree.Element, tag_name: str) -> str | None:
    child = _first_child(element, tag_name)
    if child is None:
        return None
    text = (child.text or "").strip()
    return text or None


def _child_text_any(element: ElementTree.Element, tag_names: tuple[str, ...]) -> str | None:
    for tag_name in tag_names:
        text = _child_text(element, tag_name)
        if text is not None:
            return text
    return None


def _normalize_feed_urls(feeds: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_url in feeds:
        if not isinstance(raw_url, str):
            raise NewsAdapterError("news feed URL entries must be strings")
        url = raw_url.strip()
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise NewsAdapterError(f"news feed URL must be an absolute http(s) URL: {raw_url}")
        normalized.append(url)
    return tuple(dict.fromkeys(normalized))


def _parse_datetime(value: str | None, *, fallback: datetime) -> datetime:
    if value is None:
        return fallback

    text = value.strip()
    if not text:
        return fallback

    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, IndexError):
            return fallback

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _normalize_link(link_value: str | None, *, feed_url: str) -> str | None:
    if link_value is None:
        return None
    text = link_value.strip()
    if not text:
        return None

    resolved = urljoin(feed_url, text)
    parsed = urlparse(resolved)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return resolved


def _atom_entry_link(entry: ElementTree.Element) -> str | None:
    first_link: str | None = None
    for link_element in _iter_children(entry, "link"):
        href = (link_element.attrib.get("href") or "").strip()
        if not href:
            continue

        if first_link is None:
            first_link = href

        relation = (link_element.attrib.get("rel") or "alternate").strip().lower()
        if relation in ("alternate", ""):
            return href
    return first_link


def _fetch_xml(url: str, *, user_agent: str) -> ElementTree.Element:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise NewsAdapterError(f"Failed to fetch feed: {url}") from exc

    try:
        return ElementTree.fromstring(payload)
    except ElementTree.ParseError as exc:
        raise NewsAdapterError(f"Feed XML was invalid: {url}") from exc


def _source_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").strip()
    return host or "RSS Feed"


def _parse_rss_feed(*, root: ElementTree.Element, feed_url: str, fetched_at: datetime) -> list[Headline]:
    channel = _first_child(root, "channel")
    if channel is None:
        raise NewsAdapterError(f"RSS feed was missing channel: {feed_url}")

    default_source = _child_text(channel, "title") or _source_name_from_url(feed_url)
    headlines: list[Headline] = []

    for item in _iter_children(channel, "item"):
        title = _child_text(item, "title")
        if title is None:
            continue

        link = _normalize_link(
            _child_text_any(item, ("link", "guid")),
            feed_url=feed_url,
        )
        if link is None:
            continue

        source = _child_text(item, "source") or default_source
        published_at = _parse_datetime(
            _child_text_any(item, ("pubDate", "published", "updated", "date")),
            fallback=fetched_at,
        )
        headlines.append(
            Headline(
                title=title,
                source=source,
                url=link,
                published_at=published_at,
            )
        )
    return headlines


def _parse_atom_feed(*, root: ElementTree.Element, feed_url: str, fetched_at: datetime) -> list[Headline]:
    default_source = _child_text(root, "title") or _source_name_from_url(feed_url)
    headlines: list[Headline] = []

    for entry in _iter_children(root, "entry"):
        title = _child_text(entry, "title")
        if title is None:
            continue

        link = _normalize_link(_atom_entry_link(entry), feed_url=feed_url)
        if link is None:
            continue

        source = default_source
        source_element = _first_child(entry, "source")
        if source_element is not None:
            source_title = _child_text(source_element, "title")
            if source_title is not None:
                source = source_title

        published_at = _parse_datetime(
            _child_text_any(entry, ("published", "updated")),
            fallback=fetched_at,
        )
        headlines.append(
            Headline(
                title=title,
                source=source,
                url=link,
                published_at=published_at,
            )
        )
    return headlines


def _parse_feed(*, feed_url: str, user_agent: str, fetched_at: datetime) -> list[Headline]:
    root = _fetch_xml(feed_url, user_agent=user_agent)
    root_tag = _local_name(root.tag)
    if root_tag == "rss":
        return _parse_rss_feed(root=root, feed_url=feed_url, fetched_at=fetched_at)
    if root_tag == "feed":
        return _parse_atom_feed(root=root, feed_url=feed_url, fetched_at=fetched_at)
    raise NewsAdapterError(f"Unsupported feed format at {feed_url}")


def _dedupe_and_sort(headlines: list[Headline]) -> list[Headline]:
    ordered = sorted(
        headlines,
        key=lambda headline: (
            headline.published_at,
            headline.source.casefold(),
            headline.title.casefold(),
        ),
        reverse=True,
    )
    seen: set[tuple[str, str]] = set()
    deduped: list[Headline] = []
    for headline in ordered:
        key = (headline.url, headline.title.casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(headline)
    return deduped


class RssNewsAdapter:
    def __init__(
        self,
        *,
        feeds: Iterable[str],
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._feeds = _normalize_feed_urls(feeds)
        self._user_agent = user_agent.strip() or DEFAULT_USER_AGENT

    def get_headlines(self, *, max_items: int = 8) -> list[Headline]:
        limit = max(1, int(max_items))
        if not self._feeds:
            return []

        fetched_at = datetime.now(timezone.utc)
        combined: list[Headline] = []
        errors: list[str] = []
        for feed_url in self._feeds:
            try:
                combined.extend(
                    _parse_feed(
                        feed_url=feed_url,
                        user_agent=self._user_agent,
                        fetched_at=fetched_at,
                    )
                )
            except NewsAdapterError as exc:
                errors.append(str(exc))
                continue

        if not combined and errors:
            error_preview = "; ".join(errors)
            raise NewsAdapterError(f"Unable to load any feeds: {error_preview}")

        deduped = _dedupe_and_sort(combined)
        return deduped[:limit]
