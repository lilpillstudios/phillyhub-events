#!/usr/bin/env python3
"""
PhillyHub Event Scraper v2.0
Lil Pill Studios © 2026

Architecture:
  Visit Philly (anchor-link h2) → structured events
  DiscoverPHL (link index) → follow visitphilly URLs → structured events
  Soccer Matches (hardcoded, protected)
  City Events (phila.gov fallback)
  manual_events.json (Z's curated, priority boost)
       ↓
  Merge + Dedup (protected wins) + Priority Sort → events.json
"""

import json, re, sys, hashlib, argparse, time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "PhillyHub-EventScraper/2.0 (Lil Pill Studios; lilpillstudios@gmail.com)"}
REQUEST_TIMEOUT = 15
FOLLOW_DELAY = 1

VISITPHILLY_URL = "https://www.visitphilly.com/articles/philadelphia/events-festivals-2026/"
DISCOVERPHL_URL = "https://www.discoverphl.com/blog-post/philadelphia-2026/"

VENUE_GEO = {
    "lincoln financial field":(39.906,-75.168),"philadelphia stadium":(39.906,-75.168),
    "citizens bank park":(39.9061,-75.1665),"wells fargo center":(39.9012,-75.172),
    "xfinity mobile arena":(39.9012,-75.172),"benjamin franklin parkway":(39.963,-75.175),
    "independence hall":(39.9489,-75.15),"historic district":(39.9489,-75.15),
    "old city":(39.951,-75.144),"lemon hill":(39.9715,-75.183),
    "fairmount park":(39.977,-75.2),"mann center":(39.977,-75.2105),
    "highmark mann":(39.977,-75.2105),"philadelphia museum of art":(39.9656,-75.181),
    "art museum":(39.9656,-75.181),"museum of the american revolution":(39.9483,-75.1464),
    "franklin institute":(39.9582,-75.1736),"the franklin institute":(39.9582,-75.1736),
    "pennsylvania convention center":(39.9545,-75.1597),"convention center":(39.9545,-75.1597),
    "city hall":(39.9524,-75.1636),"reading terminal market":(39.9533,-75.1592),
    "rittenhouse square":(39.9496,-75.1718),"penn's landing":(39.9459,-75.1416),
    "delaware river waterfront":(39.9459,-75.1416),"national constitution center":(39.9534,-75.1491),
    "national liberty museum":(39.949,-75.147),"please touch museum":(39.9797,-75.2094),
    "aronimink golf club":(39.9835,-75.4135),"merion golf club":(40.0032,-75.3043),
    "logan circle":(39.9571,-75.1709),"logan square":(39.9571,-75.1709),
    "malcolm x park":(39.957,-75.159),"sports complex":(39.906,-75.168),
    "penn museum":(39.9497,-75.1911),"franklin square":(39.9534,-75.1501),
    "betsy ross house":(39.9529,-75.1446),"the fillmore":(39.967,-75.134),
    "african american museum":(39.9536,-75.1515),"south philadelphia":(39.93,-75.17),
    "midtown village":(39.949,-75.161),"science history institute":(39.9533,-75.1529),
    "clay studio":(39.951,-75.139),"belmont mansion":(39.978,-75.202),
    "freedom mortgage pavilion":(39.9436,-75.132),
}

SOCCER_KW = ["soccer","match","brazil vs","france vs","croatia vs","ghana","ivory coast vs","ecuador","haiti","curaçao","curacao","round of 16","fan festival","world cup"]
A250_KW = ["250th","semiquincentennial","52 weeks","firsts","first-ival","red white blue","wawa welcome","declaration","bells across","ring it on","flag fest","founding futures","ted democracy"]
SPORTS_KW = ["mlb","all-star","pga","championship","ncaa","basketball","cycling","golf"]
ARTS_KW = ["art","museum","exhibition","exhibit","gallery","mural","what now","artphilly","flower show","lantern","ministry of awe","ballet","orchestra","film festival"]
PARADE_KW = ["parade","juneteenth","odunde","procession"]
FIREWORKS_KW = ["fireworks","july 4","fourth of july","independence day"]
FESTIVAL_KW = ["festival","fest","carnival","summerfest"]

def categorize(title, desc=""):
    t = (title+" "+desc).lower()
    if any(k in t for k in FIREWORKS_KW): return "fireworks"
    if any(k in t for k in SOCCER_KW): return "fifa"
    if any(k in t for k in PARADE_KW): return "parade"
    if any(k in t for k in A250_KW): return "america250"
    if any(k in t for k in SPORTS_KW): return "concert"
    if any(k in t for k in ARTS_KW): return "festival"
    if any(k in t for k in FESTIVAL_KW): return "festival"
    return "america250"

def geocode(v):
    if not v: return 39.9524,-75.1636
    vl = v.lower().strip()
    for k,c in VENUE_GEO.items():
        if k in vl: return c
    for k,c in VENUE_GEO.items():
        w = k.split()
        if len(w)>=2 and all(x in vl for x in w[:2]): return c
    return 39.9524,-75.1636

def make_id(title, date): return "ev_"+hashlib.md5(f"{title.lower().strip()}-{date}".encode()).hexdigest()[:8]

def parse_date(s):
    if not s: return None
    s = re.sub(r'\s+',' ',s.strip())
    s = re.sub(r'^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\w*,?\s*','',s)
    for fmt in ["%B %d, %Y","%b %d, %Y","%Y-%m-%d","%m/%d/%Y","%B %d","%b %d","%B %Y"]:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.year<2000: dt=dt.replace(year=2026)
            return dt.strftime("%Y-%m-%d")
        except ValueError: continue
    m = re.search(r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})(?:,?\s*(\d{4}))?',s,re.I)
    if m:
        try: return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3) or '2026'}","%B %d %Y").strftime("%Y-%m-%d")
        except:
            try: return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3) or '2026'}","%b %d %Y").strftime("%Y-%m-%d")
            except: pass
    return None

def parse_range(s):
    if not s: return None,None
    parts = re.split(r'\s*[-–—]+\s*',s,maxsplit=1)
    return parse_date(parts[0]), parse_date(parts[1]) if len(parts)>1 else None

def fetch(url, verbose=False):
    try:
        r = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return BeautifulSoup(r.text,"html.parser")
    except Exception as e:
        if verbose: print(f"  FETCH ERROR {url[:60]}: {e}",file=sys.stderr)
        return None

# ═══ SOURCE 1: Visit Philly ═══
def scrape_visitphilly(verbose=False):
    events = []
    if verbose: print("[visitphilly] Fetching...")
    soup = fetch(VISITPHILLY_URL, verbose)
    if not soup: return events
    content = soup.find("article") or soup.find("main") or soup
    for h in content.find_all("h2"):
        title = h.get_text(strip=True)
        link = h.find("a")
        if not link or not link.get("href"):
            if verbose: print(f"  SKIP (section header): {title[:50]}")
            continue
        href = link["href"]
        if len(title)<5 or len(title)>200: continue
        date_text,end_date,venue,addr,desc_parts = "","","","",[],
        for sib in h.find_next_siblings():
            if sib.name=="h2": break
            t = sib.get_text(strip=True)
            if not t or len(t)<3: continue
            tl = t.lower()
            if any(s in tl for s in ["read more","share","sponsored"]): continue
            if not date_text and re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d',t):
                date_text=t; continue
            if not date_text and "now open" in tl:
                date_text="January 1, 2026"; continue
            if "where:" in tl:
                raw = re.sub(r'(?i)where:\s*','',t).strip()
                venue = raw.split(',')[0].strip(); addr=raw; continue
            if len(t)>30: desc_parts.append(t)
        start,end = parse_range(date_text)
        if not start: start = parse_date(date_text)
        if not start:
            if verbose: print(f"  SKIP (no date): {title[:50]}")
            continue
        desc = " ".join(desc_parts)[:400]
        lat,lng = geocode(venue or title)
        ev = {"id":make_id(title,start),"title":title[:150],"date":start,"time":"Various",
              "venue":venue[:150] or "Philadelphia","addr":addr[:200],"lat":lat,"lng":lng,
              "cat":categorize(title,desc),"free":"free" in (title+" "+desc).lower(),
              "description":desc,"source":"visitphilly.com","link":href,"priority":1}
        if end: ev["end_date"]=end
        events.append(ev)
        if verbose: print(f"  EVENT: {title[:45]} | {start} | {venue[:25]}")
    if verbose: print(f"[visitphilly] Total: {len(events)}")
    return events

# ═══ SOURCE 2: DiscoverPHL (link-following) ═══
def scrape_discoverphl(existing_urls=None, verbose=False):
    events = []
    existing_urls = existing_urls or set()
    if verbose: print("[discoverphl] Fetching index...")
    soup = fetch(DISCOVERPHL_URL, verbose)
    if not soup: return events
    content = soup.find("article") or soup.find("main") or soup
    vp_urls = set()
    for a in content.find_all("a",href=True):
        href,text = a["href"],a.get_text(strip=True)
        if not href or not text or len(text)<5: continue
        parsed = urlparse(href)
        if "visitphilly.com" in parsed.netloc and ("/things-to-do/" in parsed.path or "/events/" in parsed.path):
            if href not in existing_urls:
                vp_urls.add(href)
    if verbose: print(f"[discoverphl] Found {len(vp_urls)} VP URLs to follow")
    for url in list(vp_urls)[:15]:
        if verbose: print(f"  Following: {url[:70]}")
        time.sleep(FOLLOW_DELAY)
        psoup = fetch(url, verbose)
        if not psoup: continue
        ev = _parse_vp_page(psoup, url, verbose)
        if ev:
            ev["source"]="discoverphl→visitphilly"
            events.append(ev)
    if verbose: print(f"[discoverphl] Total from following: {len(events)}")
    return events

def _parse_vp_page(soup, url, verbose=False):
    try:
        h1 = soup.find("h1")
        if not h1: return None
        title = h1.get_text(strip=True)
        if len(title)<5: return None
        text = soup.get_text()
        dm = re.search(r'((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:,?\s*\d{4})?)',text)
        date = parse_date(dm.group(1)) if dm else "2026-06-01"
        venue,addr = "",""
        ae = soup.find(string=re.compile(r'Philadelphia,?\s*PA',re.I))
        if ae: addr=ae.strip()[:200]; venue=addr.split(',')[0].strip()
        md = soup.find("meta",{"name":"description"})
        desc = md["content"][:400] if md and md.get("content") else ""
        if not desc:
            for p in soup.find_all("p"):
                pt=p.get_text(strip=True)
                if len(pt)>50: desc=pt[:400]; break
        lat,lng = geocode(venue or title)
        return {"id":make_id(title,date),"title":title[:150],"date":date,"time":"Various",
                "venue":venue[:150] or "Philadelphia","addr":addr[:200],"lat":lat,"lng":lng,
                "cat":categorize(title,desc),"free":"free" in (title+" "+desc).lower(),
                "description":desc,"link":url,"priority":1}
    except Exception as e:
        if verbose: print(f"  PARSE ERROR: {e}",file=sys.stderr)
        return None

# ═══ SOURCE 3: Soccer Matches (protected) ═══
def get_soccer():
    ms = [
        ("Ivory Coast vs Ecuador","2026-06-14","7:00 PM","Group E opener."),
        ("Brazil vs Haiti","2026-06-19","9:00 PM","Group C. Brazil's first match."),
        ("France vs Playoff Winner","2026-06-22","5:00 PM","Group I. France faces the playoff winner."),
        ("Curaçao vs Ivory Coast","2026-06-25","4:00 PM","Group E final matchday."),
        ("Croatia vs Ghana","2026-06-27","5:00 PM","Group L. Last group stage in Philadelphia."),
        ("Round of 16 Match","2026-07-04","5:00 PM","Knockout round on America's 250th Anniversary."),
    ]
    evs = [{"id":make_id(t,d),"title":t,"date":d,"time":tm,"venue":"Philadelphia Stadium (Lincoln Financial Field)",
            "addr":"1 Lincoln Financial Field Way","lat":39.906,"lng":-75.168,"cat":"fifa","free":False,
            "description":desc,"source":"hardcoded","ticketUrl":"https://www.fifa.com/tickets",
            "priority":5,"protected":True} for t,d,tm,desc in ms]
    evs.append({"id":make_id("Soccer Fan Festival at Lemon Hill","2026-06-11"),
        "title":"Soccer Fan Festival at Lemon Hill","date":"2026-06-11","end_date":"2026-07-13",
        "time":"All Day","venue":"Lemon Hill, Fairmount Park","addr":"Sedgley Dr, Fairmount Park",
        "lat":39.9715,"lng":-75.183,"cat":"fifa","free":True,
        "description":"5-week watch party festival. Up to 25K daily. Big screens, food, music.",
        "source":"hardcoded","priority":5,"protected":True})
    return evs

# ═══ SOURCE 4: City Events ═══
def get_city():
    raw = [
        ("52 Weeks of Firsts","2026-01-01","2026-12-31","Weekly","Citywide","Various",39.9524,-75.1636,"america250",True,"Free weekly events honoring Philly firsts. New neighborhood each Saturday."),
        ("Red, White & Blue To-Do","2026-06-28",None,"All Day","Historic District","Independence Mall",39.9489,-75.15,"america250",True,"Parades, concerts in America's most historic square mile."),
        ("Wawa Welcome America","2026-06-19","2026-07-04","All Day","Benjamin Franklin Pkwy","Benjamin Franklin Parkway",39.963,-75.175,"america250",True,"16 days from Juneteenth to July 4th. Concerts, parades, fireworks."),
        ("July 4th Fireworks & Concert","2026-07-04",None,"8:00 PM","Art Museum / Parkway","2600 Benjamin Franklin Pkwy",39.9656,-75.181,"fireworks",True,"Nation's biggest July 4th event. Concert + fireworks."),
        ("MLB All-Star Game","2026-07-14",None,"7:00 PM","Citizens Bank Park","1 Citizens Bank Way",39.9061,-75.1665,"concert",False,"Baseball returns to Philly for the first time in 30 years."),
        ("Juneteenth Parade & Festival","2026-06-21",None,"10:00 AM","Malcolm X Park","Pine St & 52nd St",39.957,-75.159,"parade",True,"Music, dance, food, celebration of freedom."),
        ("A Nation of Artists","2026-04-12","2026-09-05","10:00 AM","Philadelphia Museum of Art","2600 Benjamin Franklin Pkwy",39.9656,-75.181,"festival",False,"1,000+ works across PMA and PAFA. Four centuries of American art."),
        ("PGA Championship","2026-05-11","2026-05-17","All Day","Aronimink Golf Club","3600 St Davids Rd, Newtown Square",39.9835,-75.4135,"concert",False,"One of golf's four majors."),
        ("Philadelphia Flower Show","2026-02-28","2026-03-08","10:00 AM","Convention Center","1101 Arch St",39.9545,-75.1597,"festival",False,"'Rooted: Origins of American Gardening.'"),
    ]
    evs = []
    for r in raw:
        ev = {"id":make_id(r[0],r[1]),"title":r[0],"date":r[1],"time":r[3],"venue":r[4],"addr":r[5],
              "lat":r[6],"lng":r[7],"cat":r[8],"free":r[9],"description":r[10],"source":"city","priority":3}
        if r[2]: ev["end_date"]=r[2]
        evs.append(ev)
    return evs

# ═══ SOURCE 5: Manual Events ═══
def load_manual(verbose=False):
    events = []
    p = Path(__file__).parent/"manual_events.json"
    if not p.exists():
        if verbose: print("[manual] No file found")
        return events
    try:
        for ev in json.loads(p.read_text()):
            lat,lng = ev.get("lat"),ev.get("lng")
            if not lat or not lng: lat,lng = geocode(ev.get("venue",""))
            e = {"id":make_id(ev["title"],ev["date"]),"title":ev["title"],"date":ev["date"],
                 "time":ev.get("time","Various"),"venue":ev.get("venue","Philadelphia"),
                 "addr":ev.get("addr",""),"lat":lat,"lng":lng,
                 "cat":ev.get("cat") or categorize(ev["title"],ev.get("desc","")),
                 "free":ev.get("free",False),"description":ev.get("desc",""),
                 "source":"manual","priority":ev.get("priority",10)}
            if "end_date" in ev: e["end_date"]=ev["end_date"]
            events.append(e)
        if verbose: print(f"[manual] Loaded {len(events)}")
    except Exception as ex: print(f"[manual] ERROR: {ex}",file=sys.stderr)
    return events

# ═══ Dedup + Filter + Sort ═══
def dedup(events):
    seen = {}
    for ev in events:
        key = re.sub(r"[^a-z0-9 ]","",ev["title"].lower()).strip()[:40]+"-"+ev["date"]
        if key in seen:
            ex = seen[key]
            if ev.get("protected") and not ex.get("protected"): seen[key]=ev
            elif ex.get("protected"): pass
            elif ev.get("priority",1)>ex.get("priority",1): seen[key]=ev
            elif ev.get("priority",1)==ex.get("priority",1) and len(ev.get("description",""))>len(ex.get("description","")): seen[key]=ev
        else: seen[key]=ev
    return list(seen.values())

def filter_future(events):
    today = datetime.now().strftime("%Y-%m-%d")
    return [e for e in events if (e.get("end_date") or e["date"])>=today]

def sort_events(events):
    return sorted(events, key=lambda e:(e["date"],-e.get("priority",1)))

# ═══ Main ═══
def main():
    ap = argparse.ArgumentParser(description="PhillyHub Event Scraper v2.0")
    ap.add_argument("--output","-o",default="events.json")
    ap.add_argument("--verbose","-v",action="store_true")
    ap.add_argument("--dry-run",action="store_true")
    args = ap.parse_args()

    print("═══ PhillyHub Event Scraper v2.0 ═══\n")
    all_ev = []

    soccer = get_soccer(); all_ev.extend(soccer); print(f"  ⚽ Soccer: {len(soccer)}")
    city = get_city(); all_ev.extend(city); print(f"  🏛  City: {len(city)}")
    manual = load_manual(args.verbose); all_ev.extend(manual); print(f"  ✏️  Manual: {len(manual)}")
    vp = scrape_visitphilly(args.verbose); all_ev.extend(vp); print(f"  🌐 Visit Philly: {len(vp)}")
    vp_urls = {e.get("link","") for e in vp if e.get("link")}
    dphl = scrape_discoverphl(vp_urls,args.verbose); all_ev.extend(dphl); print(f"  🔗 DiscoverPHL: {len(dphl)}")

    print(f"\n  Raw total: {len(all_ev)}")
    dd = dedup(all_ev); print(f"  After dedup: {len(dd)}")
    fut = filter_future(dd); print(f"  Future: {len(fut)}")
    final = sort_events(fut)

    if args.dry_run:
        print("\n═══ DRY RUN ═══")
        for e in final:
            p = " 🔒" if e.get("protected") else ""
            print(f"  {e['date']} | {e['title'][:45]}{p} [p={e.get('priority',1)}] ({e['source']})")
        return

    clean = [{k:v for k,v in e.items() if k not in ["protected","link"]} for e in final]
    out = {"version":2,"scraped_at":datetime.now().astimezone().isoformat(),"event_count":len(clean),"events":clean}
    op = Path(args.output)
    op.write_text(json.dumps(out,indent=2,ensure_ascii=False))
    print(f"\n  Written: {op} ({op.stat().st_size:,} bytes) ✅")

if __name__=="__main__": main()
