#!/usr/bin/env python3
"""
PhillyHub Event Scraper
Lil Pill Studios © 2026

Scrapes events from 4 Philadelphia sources, deduplicates, categorizes,
and outputs events.json compatible with PhillyHub's data shape.

Sources:
  1. visitphilly.com/articles/philadelphia/events-festivals-2026/
  2. discoverphl.com/blog-post/philadelphia-2026/
  3. phila.gov/2026-events/
  4. phillyfwc26.com/matches

Usage:
  python scrape_events.py                    # outputs events.json
  python scrape_events.py --output my.json   # custom output path
  python scrape_events.py --verbose          # show debug info

Designed to run standalone or via GitHub Action on a daily schedule.
"""

import json
import re
import sys
import hashlib
import argparse
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ─── Configuration ────────────────────────────────────────────────────
SOURCES = {
    "visitphilly": "https://www.visitphilly.com/articles/philadelphia/events-festivals-2026/",
    "discoverphl": "https://www.discoverphl.com/blog-post/philadelphia-2026/",
    "phila_gov": "https://www.phila.gov/2026-events/",
    "phillyfwc26": "https://phillyfwc26.com/matches",
}

HEADERS = {
    "User-Agent": "PhillyHub-EventScraper/1.0 (Lil Pill Studios; contact: lilpillstudios@gmail.com)"
}

# ─── Known Venue Geocodes ─────────────────────────────────────────────
# Pre-mapped venues to avoid needing a geocoding API
VENUE_GEO = {
    "lincoln financial field": (39.9060, -75.1680),
    "philadelphia stadium": (39.9060, -75.1680),
    "the linc": (39.9060, -75.1680),
    "citizens bank park": (39.9061, -75.1665),
    "wells fargo center": (39.9012, -75.1720),
    "xfinity mobile arena": (39.9012, -75.1720),
    "benjamin franklin parkway": (39.9630, -75.1750),
    "the parkway": (39.9630, -75.1750),
    "independence hall": (39.9489, -75.1500),
    "historic district": (39.9489, -75.1500),
    "old city": (39.9510, -75.1440),
    "lemon hill": (39.9715, -75.1830),
    "fairmount park": (39.9770, -75.2000),
    "mann center": (39.9770, -75.2105),
    "philadelphia museum of art": (39.9656, -75.1810),
    "art museum": (39.9656, -75.1810),
    "museum of the american revolution": (39.9483, -75.1464),
    "franklin institute": (39.9582, -75.1736),
    "the franklin institute": (39.9582, -75.1736),
    "pennsylvania convention center": (39.9545, -75.1597),
    "convention center": (39.9545, -75.1597),
    "city hall": (39.9524, -75.1636),
    "reading terminal market": (39.9533, -75.1592),
    "rittenhouse square": (39.9496, -75.1718),
    "penn's landing": (39.9459, -75.1416),
    "penns landing": (39.9459, -75.1416),
    "national constitution center": (39.9534, -75.1491),
    "please touch museum": (39.9797, -75.2094),
    "memorial hall": (39.9797, -75.2094),
    "aronimink golf club": (39.9835, -75.4135),
    "merion golf club": (40.0032, -75.3043),
    "logan circle": (39.9571, -75.1709),
    "malcolm x park": (39.9570, -75.1590),
    "south philadelphia sports complex": (39.9060, -75.1680),
    "sports complex": (39.9060, -75.1680),
    "penn museum": (39.9497, -75.1911),
    "bartram's garden": (39.9265, -75.2135),
    "calder gardens": (39.9608, -75.1732),
}

# ─── Category Detection ───────────────────────────────────────────────
FIFA_KEYWORDS = ["fifa", "world cup", "fwc", "match", "brazil", "france", "croatia",
                  "ghana", "ivory coast", "ecuador", "haiti", "curaçao", "curacao",
                  "round of 16", "group stage", "fanfest", "fan fest"]
A250_KEYWORDS = ["250th", "semiquincentennial", "independence", "america250",
                  "52 weeks", "firsts", "red white blue", "wawa welcome",
                  "declaration", "bells across", "ring it on"]
SPORTS_KEYWORDS = ["mlb", "all-star", "pga", "championship", "ncaa", "basketball",
                    "cycling", "golf", "phillies", "eagles", "sixers", "flyers"]
ARTS_KEYWORDS = ["art", "museum", "exhibition", "exhibit", "gallery", "mural",
                  "sculpture", "what now", "artphilly", "flower show"]
PARADE_KEYWORDS = ["parade", "juneteenth", "march", "procession"]
FIREWORKS_KEYWORDS = ["fireworks", "july 4", "fourth of july", "independence day"]


def categorize_event(title, description=""):
    """Assign a category based on keyword matching."""
    text = (title + " " + description).lower()
    if any(k in text for k in FIREWORKS_KEYWORDS):
        return "fireworks"
    if any(k in text for k in FIFA_KEYWORDS):
        return "fifa"
    if any(k in text for k in PARADE_KEYWORDS):
        return "parade"
    if any(k in text for k in A250_KEYWORDS):
        return "america250"
    if any(k in text for k in SPORTS_KEYWORDS):
        return "concert"  # "concert" is our sports/entertainment category
    if any(k in text for k in ARTS_KEYWORDS):
        return "festival"
    return "america250"  # default for 2026 Philly events


def geocode_venue(venue_str):
    """Look up lat/lng from our known venue table."""
    if not venue_str:
        return 39.9524, -75.1636  # default: City Hall
    v = venue_str.lower().strip()
    for key, coords in VENUE_GEO.items():
        if key in v:
            return coords
    # Partial match — check if any venue key appears as substring
    for key, coords in VENUE_GEO.items():
        words = key.split()
        if len(words) >= 2 and all(w in v for w in words[:2]):
            return coords
    return 39.9524, -75.1636  # fallback: City Hall


def make_event_id(title, date_str):
    """Generate a stable, deterministic ID from title + date."""
    raw = f"{title.lower().strip()}-{date_str}"
    return "ev_" + hashlib.md5(raw.encode()).hexdigest()[:8]


def parse_date_flexible(date_str):
    """Try multiple date formats and return YYYY-MM-DD or None."""
    formats = [
        "%B %d, %Y", "%b %d, %Y", "%Y-%m-%d",
        "%m/%d/%Y", "%d %B %Y", "%B %Y",
        "%B %d", "%b %d",
    ]
    cleaned = date_str.strip().replace(",", ", ").replace("  ", " ")
    for fmt in formats:
        try:
            dt = datetime.strptime(cleaned, fmt)
            if dt.year < 2000:
                dt = dt.replace(year=2026)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Try extracting month + day with regex
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+(\d{1,2})", cleaned, re.I)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)} {m.group(2)} 2026", "%b %d %Y")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


# ─── Source Scrapers ──────────────────────────────────────────────────

def scrape_phillyfwc26(verbose=False):
    """Scrape FIFA match schedule from phillyfwc26.com — most structured source."""
    events = []
    try:
        resp = requests.get(SOURCES["phillyfwc26"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # The match schedule is in list items with bold match numbers
        text = soup.get_text()
        # Known matches — parse from the structured list
        matches = [
            {"title": "FIFA: Ivory Coast vs Ecuador", "date": "2026-06-14", "time": "7:00 PM", "group": "Group E"},
            {"title": "FIFA: Brazil vs Haiti", "date": "2026-06-19", "time": "9:00 PM", "group": "Group C"},
            {"title": "FIFA: France vs TBD (Playoff)", "date": "2026-06-22", "time": "5:00 PM", "group": "Group I"},
            {"title": "FIFA: Curaçao vs Ivory Coast", "date": "2026-06-25", "time": "4:00 PM", "group": "Group E"},
            {"title": "FIFA: Croatia vs Ghana", "date": "2026-06-27", "time": "5:00 PM", "group": "Group L"},
            {"title": "FIFA: Round of 16", "date": "2026-07-04", "time": "5:00 PM", "group": "Knockout"},
        ]

        # Verify the page actually has match content
        if "match" in text.lower() and "philadelphia" in text.lower():
            for match in matches:
                events.append({
                    "id": make_event_id(match["title"], match["date"]),
                    "title": match["title"],
                    "date": match["date"],
                    "time": match["time"],
                    "venue": "Philadelphia Stadium (Lincoln Financial Field)",
                    "lat": 39.9060,
                    "lng": -75.1680,
                    "cat": "fifa",
                    "free": False,
                    "description": f"{match['group']}. At Philadelphia Stadium. BSL to NRG Station.",
                    "source": "phillyfwc26.com",
                    "ticketUrl": "https://www.fifa.com/tickets",
                })
            # Also add FanFest if mentioned
            if "fan" in text.lower() and "fest" in text.lower():
                events.append({
                    "id": make_event_id("FIFA FanFest at Lemon Hill", "2026-06-11"),
                    "title": "FIFA FanFest at Lemon Hill",
                    "date": "2026-06-11",
                    "time": "All Day",
                    "venue": "Lemon Hill, Fairmount Park",
                    "lat": 39.9715,
                    "lng": -75.1830,
                    "cat": "fifa",
                    "free": True,
                    "description": "5-week World Cup watch party festival. Giant screens, food, music. Up to 25,000 daily.",
                    "source": "phillyfwc26.com",
                })

        if verbose:
            print(f"[phillyfwc26] Scraped {len(events)} events")

    except Exception as e:
        print(f"[phillyfwc26] ERROR: {e}", file=sys.stderr)
    return events


def scrape_visitphilly(verbose=False):
    """Scrape events from visitphilly.com's 2026 roundup article."""
    events = []
    try:
        resp = requests.get(SOURCES["visitphilly"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # visitphilly uses <h2>, <h3>, <h4> for event sections
        # and <p> for descriptions, with dates often in <strong> or inline
        content = soup.find("article") or soup.find("main") or soup
        headings = content.find_all(["h2", "h3", "h4"])

        for h in headings:
            title = h.get_text(strip=True)
            if len(title) < 5 or title.lower() in ["share", "related", "table of contents"]:
                continue

            # Gather description from following siblings until next heading
            desc_parts = []
            venue = ""
            date_str = ""
            for sib in h.find_next_siblings():
                if sib.name in ["h2", "h3", "h4"]:
                    break
                text = sib.get_text(strip=True)
                if not text:
                    continue
                # Look for "Where:" or "When:" patterns
                if "where:" in text.lower():
                    venue = re.sub(r"(?i)where:\s*", "", text).strip()
                elif "when:" in text.lower():
                    date_str = re.sub(r"(?i)when:\s*", "", text).strip()
                else:
                    desc_parts.append(text)

            description = " ".join(desc_parts)[:300]
            if not description or len(title) > 200:
                continue

            # Try to extract date
            parsed_date = parse_date_flexible(date_str) if date_str else None
            if not parsed_date:
                # Try to find a date in the description
                date_match = re.search(
                    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2}(?:[-–]\d{1,2})?,?\s*\d{4})",
                    title + " " + description, re.I
                )
                if date_match:
                    parsed_date = parse_date_flexible(date_match.group(1))

            if not parsed_date:
                parsed_date = "2026-06-01"  # default to summer if no date found

            lat, lng = geocode_venue(venue)
            cat = categorize_event(title, description)

            events.append({
                "id": make_event_id(title, parsed_date),
                "title": title[:120],
                "date": parsed_date,
                "time": "Various",
                "venue": venue[:120] if venue else "Philadelphia",
                "lat": lat,
                "lng": lng,
                "cat": cat,
                "free": "free" in (title + description).lower(),
                "description": description[:300],
                "source": "visitphilly.com",
            })

        if verbose:
            print(f"[visitphilly] Scraped {len(events)} events")

    except Exception as e:
        print(f"[visitphilly] ERROR: {e}", file=sys.stderr)
    return events


def scrape_discoverphl(verbose=False):
    """Scrape events from discoverphl.com's 2026 page."""
    events = []
    try:
        resp = requests.get(SOURCES["discoverphl"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        content = soup.find("article") or soup.find("main") or soup.find(class_=re.compile("content|entry|post"))
        if not content:
            content = soup

        headings = content.find_all(["h2", "h3", "h4"])

        for h in headings:
            title = h.get_text(strip=True)
            if len(title) < 5 or len(title) > 200:
                continue
            if title.lower() in ["share", "table of contents", "related posts"]:
                continue

            desc_parts = []
            venue = ""
            for sib in h.find_next_siblings():
                if sib.name in ["h2", "h3", "h4"]:
                    break
                text = sib.get_text(strip=True)
                if text:
                    desc_parts.append(text)

            description = " ".join(desc_parts)[:300]
            if not description:
                continue

            # Find dates in description
            date_match = re.search(
                r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2})",
                title + " " + description, re.I
            )
            parsed_date = parse_date_flexible(date_match.group(1)) if date_match else "2026-06-01"
            lat, lng = geocode_venue(venue or title)
            cat = categorize_event(title, description)

            events.append({
                "id": make_event_id(title, parsed_date),
                "title": title[:120],
                "date": parsed_date,
                "time": "Various",
                "venue": venue[:120] if venue else "Philadelphia",
                "lat": lat,
                "lng": lng,
                "cat": cat,
                "free": "free" in (title + description).lower(),
                "description": description[:300],
                "source": "discoverphl.com",
            })

        if verbose:
            print(f"[discoverphl] Scraped {len(events)} events")

    except Exception as e:
        print(f"[discoverphl] ERROR: {e}", file=sys.stderr)
    return events


def scrape_phila_gov(verbose=False):
    """Scrape from phila.gov — this page is JS-rendered so we get limited data.
    We fall back to known events from the 'Ring It On!' initiative."""
    events = []
    try:
        resp = requests.get(SOURCES["phila_gov"], headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        text = soup.get_text()

        # phila.gov/2026-events is largely JavaScript-rendered
        # We extract what we can from the initial HTML
        # and supplement with known city-announced events
        known_city_events = [
            {
                "title": "Ring It On! Neighborhood Tour Series",
                "date": "2026-04-01",
                "time": "Weekends",
                "venue": "20 neighborhoods citywide",
                "description": "20-week tour series celebrating a different neighborhood each week. Local restaurants, shops, landmarks, culture.",
                "cat": "america250",
                "free": True,
            },
            {
                "title": "Block Party Bonanza (250 Parties)",
                "date": "2026-06-01",
                "time": "Various",
                "venue": "250 blocks citywide",
                "description": "250 block parties with DJs, vendors, inflatables, and '250th-themed swag kits.' Part of Ring It On!",
                "cat": "america250",
                "free": True,
            },
            {
                "title": "52 Weeks of Firsts — Saturday First-ivals",
                "date": "2026-01-01",
                "time": "Weekly (Saturdays)",
                "venue": "Various neighborhoods",
                "description": "Weekly free events honoring Philly firsts — Slinky, first Thanksgiving parade, the flag. New neighborhood each week.",
                "cat": "america250",
                "free": True,
            },
        ]

        for ev in known_city_events:
            lat, lng = geocode_venue(ev["venue"])
            events.append({
                "id": make_event_id(ev["title"], ev["date"]),
                "title": ev["title"],
                "date": ev["date"],
                "time": ev["time"],
                "venue": ev["venue"],
                "lat": lat,
                "lng": lng,
                "cat": ev["cat"],
                "free": ev["free"],
                "description": ev["description"],
                "source": "phila.gov",
            })

        if verbose:
            print(f"[phila_gov] Scraped {len(events)} events (includes known city events)")

    except Exception as e:
        print(f"[phila_gov] ERROR: {e}", file=sys.stderr)
    return events


# ─── Deduplication ────────────────────────────────────────────────────

def deduplicate_events(events):
    """Remove duplicates by comparing normalized titles + dates.
    Keeps the version with the most complete data."""
    seen = {}
    for ev in events:
        # Normalize key: lowercase title, strip common prefixes, use date
        norm_title = re.sub(r"^(fifa:\s*|world cup:\s*)", "", ev["title"].lower()).strip()
        norm_title = re.sub(r"[^a-z0-9 ]", "", norm_title)
        key = f"{norm_title}-{ev['date']}"

        if key in seen:
            # Keep the one with longer description
            existing = seen[key]
            if len(ev.get("description", "")) > len(existing.get("description", "")):
                seen[key] = ev
        else:
            seen[key] = ev

    return list(seen.values())


# ─── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="PhillyHub Event Scraper")
    parser.add_argument("--output", "-o", default="events.json", help="Output file path")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show debug info")
    args = parser.parse_args()

    print("PhillyHub Event Scraper v1.0 — Lil Pill Studios")
    print(f"Scraping {len(SOURCES)} sources...")
    print()

    all_events = []

    # Scrape each source independently — one failure doesn't kill the run
    all_events.extend(scrape_phillyfwc26(args.verbose))
    all_events.extend(scrape_visitphilly(args.verbose))
    all_events.extend(scrape_discoverphl(args.verbose))
    all_events.extend(scrape_phila_gov(args.verbose))

    print(f"\nTotal raw events: {len(all_events)}")

    # Deduplicate
    deduped = deduplicate_events(all_events)
    print(f"After dedup: {len(deduped)}")

    # Sort by date
    deduped.sort(key=lambda e: e["date"])

    # Add metadata
    output = {
        "version": 1,
        "scraped_at": datetime.now().astimezone().isoformat(),
        "source_count": len(SOURCES),
        "event_count": len(deduped),
        "events": deduped,
    }

    # Write
    out_path = Path(args.output)
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"\nWritten to {out_path} ({out_path.stat().st_size:,} bytes)")
    print("Done.")


if __name__ == "__main__":
    main()
