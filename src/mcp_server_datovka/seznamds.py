"""Offline lookup against the ``seznamds`` Czech data-box directory.

``seznamds`` (https://github.com/VitexSoftware) is an optional Debian package
that ships a static, periodically-refreshed snapshot of every Czech data box
at ``/var/lib/seznamds/seznam_ds_{po,pfo,ovm}.xml`` (gzip-compressed XML,
despite the ``.xml`` extension). Searching it locally avoids hitting the
live, rate-limited ISDS fulltext-search SOAP API for routine lookups.

The snapshot can go stale between package refreshes. Every result from
:func:`search_local` is accompanied by :func:`data_age_days` so callers can
warn when the data may be outdated, rather than presenting it as live.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

SEZNAMDS_DIR = Path("/var/lib/seznamds")

# Ordered so the most common lookups (companies, then sole traders, then
# public authorities) are searched first; search_local stops once `limit`
# matches are collected.
_DATA_FILES = ("seznam_ds_po.xml", "seznam_ds_pfo.xml", "seznam_ds_ovm.xml")

_NS = "{http://seznam.gov.cz/ovm/datafile/seznam_ds/v1}"

STALE_AFTER_DAYS = 30


def data_age_days() -> int | None:
    """Age, in days, of the oldest installed seznamds data file.

    Returns None if the seznamds package isn't installed.
    """
    mtimes = [
        (SEZNAMDS_DIR / name).stat().st_mtime
        for name in _DATA_FILES
        if (SEZNAMDS_DIR / name).is_file()
    ]
    if not mtimes:
        return None
    oldest = min(mtimes)
    age = datetime.now(tz=timezone.utc) - datetime.fromtimestamp(oldest, tz=timezone.utc)
    return age.days


def _box_matches(box: ET.Element, needle: str) -> bool:
    trade_name = box.findtext(f"{_NS}name/{_NS}tradeName") or ""
    first_name = box.findtext(f"{_NS}name/{_NS}person/{_NS}firstName") or ""
    last_name = box.findtext(f"{_NS}name/{_NS}person/{_NS}lastName") or ""
    ico = box.findtext(f"{_NS}ico") or ""
    haystack = f"{trade_name} {first_name} {last_name} {ico}".lower()
    return needle in haystack


def _box_to_dict(box: ET.Element) -> dict[str, str | None]:
    return {
        "box_id": box.findtext(f"{_NS}id"),
        "type": box.findtext(f"{_NS}type"),
        "name": box.findtext(f"{_NS}name/{_NS}tradeName"),
        "ico": box.findtext(f"{_NS}ico"),
        "city": box.findtext(f"{_NS}address/{_NS}city"),
    }


def search_local(query: str, limit: int = 10) -> list[dict[str, str | None]]:
    """Search the offline seznamds directory by name, trade name, or IČO.

    Returns an empty list if the seznamds package isn't installed, or if
    nothing matches -- either way the caller should treat that as "try the
    live API instead", not as an error.
    """
    needle = query.strip().lower()
    if not needle:
        return []

    results: list[dict[str, str | None]] = []
    for filename in _DATA_FILES:
        path = SEZNAMDS_DIR / filename
        if not path.is_file():
            continue
        with gzip.open(path, "rb") as f:
            for _, elem in ET.iterparse(f):
                tag = elem.tag.rsplit("}", 1)[-1]
                if tag != "box":
                    continue
                if _box_matches(elem, needle):
                    results.append(_box_to_dict(elem))
                    if len(results) >= limit:
                        elem.clear()
                        return results
                elem.clear()
        if len(results) >= limit:
            break
    return results
