#!/usr/bin/env python3
"""ArXiv Daily Briefing generator for Illhart Observatory.
Runs entirely on GitHub Actions — no M6 dependency.
Fetches new astro-ph.EP/SR/HE/IM submissions, scores them for
RC400/MK67 relevance, writes data.json for the GitHub Pages site.
"""

import json
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET

CATEGORIES = ["astro-ph.EP", "astro-ph.SR", "astro-ph.HE", "astro-ph.IM"]

HIGH_KEYWORDS = [
    "asteroid", "neocp", "neo", "occultation", "exoplanet transit",
    "supernova", "nova", "grb", "cataclysmic variable", "lightcurve",
    "rotation period",
]
MEDIUM_KEYWORDS = [
    "variable star", "eclipsing binary", "photometry", "time series",
    "transient", "spectroscopy", "small telescope", "automated observatory",
    "pipeline",
]
NEGATIVE_KEYWORDS = [
    "radio", "submillimeter", "alma", "jwst", "dark matter",
    "cosmological", "galaxy cluster", "8m telescope", "wide-field survey",
]
SPEC_KEYWORDS = [
    "spectroscopy", "spectra", "spectrograph", "radial velocity",
    "spectral", "abundance",
]

MIN_SCORE = 3
DAYS_BACK = 3
ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom"}


def fetch_category(cat, max_retries=5):
    params = {
        "search_query": f"cat:{cat}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": 100,
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "IllhartObservatory-ArxivBriefing/1.0"}
    )

    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return ET.fromstring(resp.read())
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt < max_retries:
                wait = 20 * attempt
                print(f"{cat}: HTTP 429, retry {attempt}/{max_retries} in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            last_err = e
            if attempt < max_retries:
                wait = 20 * attempt
                print(f"{cat}: {e}, retry {attempt}/{max_retries} in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            raise
    raise last_err


def score_text(text):
    t = text.lower()
    score = 0
    for kw in HIGH_KEYWORDS:
        if kw in t:
            score += 4
    for kw in MEDIUM_KEYWORDS:
        if kw in t:
            score += 2
    for kw in NEGATIVE_KEYWORDS:
        if kw in t:
            score -= 3
    return score


def pick_instrument(text):
    t = text.lower()
    return "MK67 (future spec.)" if any(k in t for k in SPEC_KEYWORDS) else "RC400"


def tier_for(score):
    if score >= 8:
        return 1
    if score >= 4:
        return 2
    return 3


def main():
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)).date()
    seen, articles, total_fetched = set(), [], 0

    for i, cat in enumerate(CATEGORIES):
        if i > 0:
            time.sleep(5)
        try:
            root = fetch_category(cat)
        except Exception as e:
            print(f"WARNING: fetch failed for {cat} after all retries: {e}", file=sys.stderr)
            continue

        entries = root.findall("atom:entry", NS)

        for entry in entries:
            published_raw = entry.find("atom:published", NS).text
            published_date = datetime.strptime(published_raw[:10], "%Y-%m-%d").date()
            if published_date < cutoff_date:
                continue

            arxiv_id = entry.find("atom:id", NS).text.strip().rsplit("/", 1)[-1]
            if arxiv_id in seen:
                continue
            seen.add(arxiv_id)
            total_fetched += 1

            title = " ".join(entry.find("atom:title", NS).text.split())
            abstract = " ".join(entry.find("atom:summary", NS).text.split())
            authors = [a.find("atom:name", NS).text for a in entry.findall("atom:author", NS)]

            combined = f"{title} {abstract}"
            score = score_text(combined)
            if score < MIN_SCORE:
                continue

            articles.append({
                "arxiv_id": arxiv_id,
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "url": f"https://arxiv.org/abs/{arxiv_id}",
                "category": cat,
                "published": published_raw[:10],
                "score": score,
                "tier": tier_for(score),
                "instrument": pick_instrument(combined),
            })

    articles.sort(key=lambda a: a["score"], reverse=True)

    output = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "total_fetched": total_fetched,
        "relevant_count": len(articles),
        "min_score": MIN_SCORE,
        "articles": articles,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Wrote data.json: {len(articles)} relevant of {total_fetched} fetched (window: last {DAYS_BACK} days, cutoff date {cutoff_date})")


if __name__ == "__main__":
    main()
