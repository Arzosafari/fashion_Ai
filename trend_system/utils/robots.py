"""robots.txt helpers.

The trend pipeline is intentionally conservative: it only collects content that
the site owner permits for generic user agents.  ``WGSN`` is kept in the source
registry but its ``robots.txt`` disallows ``*`` — the collector therefore skips
it gracefully instead of bypassing the restriction.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# host -> robots.txt content ("" when the file is absent / unreachable)
_ROBOTS_CACHE: dict[str, str | None] = {}


def _default_user_agent() -> str:
    try:
        from trend_system.config import get_settings

        return get_settings().USER_AGENT
    except Exception:  # pragma: no cover - configuration always importable in practice
        return "FashionTrendBot/1.0 (+https://example.com/bot)"


def _fallback_is_allowed(url: str, robots_content: str, user_agent: str) -> bool:
    """Small robots parser used only when ``protego`` cannot parse the file."""
    path = urlparse(url).path or "/"
    groups: dict[str, list[tuple[str, str]]] = {}
    current: list[str] = []
    for raw_line in robots_content.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            current = [value.lower()]
            groups.setdefault(value.lower(), [])
        elif key in ("allow", "disallow") and current:
            for agent in current:
                groups.setdefault(agent, []).append((key, value))

    # Most specific user-agent group wins, otherwise the wildcard group.
    ua = (user_agent or "").lower()
    rules = None
    for agent, agent_rules in groups.items():
        if agent != "*" and agent and agent in ua:
            rules = agent_rules
            break
    if rules is None:
        rules = groups.get("*", [])

    best_len = -1
    allowed = True
    for key, value in rules:
        if not value:
            continue  # "Disallow:" (empty) means allow everything
        if path.startswith(value) and len(value) > best_len:
            best_len = len(value)
            allowed = key == "allow"
    return allowed


def is_allowed_by_robots(
    url: str,
    robots_content: str | None = None,
    user_agent: str | None = None,
) -> bool:
    """Return True when ``url`` may be fetched.

    ``robots_content=None`` means "no robots information available"; the caller
    is expected to pass fetched content when it matters.  Parsing errors fall
    back to a conservative hand-rolled parser rather than failing open.
    """
    if robots_content is None:
        return True
    ua = user_agent or _default_user_agent()
    try:
        from protego import Protego

        parser = Protego.parse(robots_content)
        return bool(parser.can_fetch(url, ua))
    except Exception as exc:  # pragma: no cover - depends on malformed input
        logger.debug("robots parse fallback for %s: %s", url, exc)
        try:
            return bool(_fallback_is_allowed(url, robots_content, ua))
        except Exception:
            return False


def robots_url_for(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}/robots.txt"


async def fetch_robots_txt(url: str, http_client, use_cache: bool = True) -> str | None:
    """Fetch and cache ``robots.txt`` for the host of ``url``.

    Returns ``None`` when the file could not be retrieved (network error or
    5xx).  A missing file (404) is cached as an empty string.
    """
    robots_url = robots_url_for(url)
    host = urlparse(url).netloc
    if use_cache and host in _ROBOTS_CACHE:
        return _ROBOTS_CACHE[host]

    try:
        response = await http_client.get(robots_url, timeout=15)
    except Exception as exc:
        logger.info("robots.txt unavailable for %s: %s", host, exc)
        return None

    if response.status_code == 200:
        content = response.text
    elif response.status_code in (401, 403):
        # Treat an access-controlled robots.txt as "not permitted".
        content = "User-agent: *\nDisallow: /\n"
    elif 400 <= response.status_code < 500:
        content = ""
    else:
        logger.info("robots.txt fetch failed for %s: HTTP %s", host, response.status_code)
        return None

    if use_cache:
        _ROBOTS_CACHE[host] = content
    return content


def clear_robots_cache() -> None:
    _ROBOTS_CACHE.clear()
