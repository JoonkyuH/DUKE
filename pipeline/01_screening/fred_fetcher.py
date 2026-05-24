"""
fred_fetcher.py
Fetches the ICE BofA US High Yield Option-Adjusted Spread from FRED.

Entry point:
    fetch_hy_spread() -> float | None

Returns the most recent BAMLH0A0HYM2 value in basis points, or None if
FRED_API_KEY is not set or the fetch fails. Result is cached in memory
for the session — only one FRED call per process.
"""

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

log = logging.getLogger(__name__)

_FRED_URL  = "https://api.stlouisfed.org/fred/series/observations"
_SERIES_ID = "BAMLH0A0HYM2"

_cache: Optional[float] = None
_cache_populated: bool  = False


def fetch_hy_spread() -> Optional[float]:
    """
    Return the most recent ICE BofA US HY OAS in basis points, or None.

    FRED reports the value in percent (e.g. "3.21" = 321 bps); this
    function multiplies by 100 before returning.
    """
    global _cache, _cache_populated
    if _cache_populated:
        return _cache

    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        log.info("FRED_API_KEY not set — HY spread unavailable")
        _cache_populated = True
        return None

    params = urllib.parse.urlencode({
        "series_id":  _SERIES_ID,
        "sort_order": "desc",
        "limit":      1,
        "file_type":  "json",
        "api_key":    api_key,
    })
    url = f"{_FRED_URL}?{params}"

    try:
        req = urllib.request.Request(url)
        req.add_unredirected_header("User-Agent", "DUKE/1.0")
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        observations = data.get("observations", [])
        if not observations:
            log.warning("FRED: no observations returned for %s", _SERIES_ID)
            _cache_populated = True
            return None

        value_str = observations[0].get("value", "")
        if not value_str or value_str == ".":
            log.warning("FRED: missing value for %s", _SERIES_ID)
            _cache_populated = True
            return None

        _cache = round(float(value_str) * 100, 1)
        _cache_populated = True
        return _cache

    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        log.warning("FRED fetch failed (HTTP %s): %s", exc.code, body)
    except Exception as exc:
        log.warning("FRED fetch failed: %s", exc)

    _cache_populated = True
    return None
