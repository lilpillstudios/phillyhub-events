# PhillyHub Event Scraper
**Lil Pill Studios © 2026**

Automated event data pipeline for the PhillyHub app. Scrapes 4 Philadelphia event sources daily and outputs a `events.json` file that the app fetches for live event data.

## Sources
- **phillyfwc26.com** — FIFA World Cup 2026 match schedule
- **visitphilly.com** — Comprehensive 2026 events roundup
- **discoverphl.com** — America250 and semiquincentennial events
- **phila.gov** — City of Philadelphia official 2026 events

## How It Works

```
[4 Sources] → scrape_events.py → events.json → GitHub repo → app fetches raw URL
                                                     ↑
                                          GitHub Action (daily 6 AM EST)
```

The app bundles a baseline `events.json` for offline use. On launch, it fetches the latest version from GitHub. If the fetch fails (no internet, server down), the bundled version is used.

## Setup

### 1. Create a GitHub repo
```bash
gh repo create phillyhub-events --public
cd phillyhub-events
cp -r /path/to/this/folder/* .
git add .
git commit -m "initial: scraper + workflow"
git push
```

### 2. Update the app's fetch URL
In `useRemoteEvents.js`, replace `YOUR_USERNAME`:
```js
const EVENTS_URL = "https://raw.githubusercontent.com/YOUR_USERNAME/phillyhub-events/main/events.json";
```

### 3. Run manually (first time)
```bash
python scrape_events.py --verbose
```
This creates `events.json`. Commit and push it.

### 4. GitHub Action runs daily
The workflow at `.github/workflows/scrape-events.yml` runs at 6 AM EST every day. It only commits if the data actually changed.

You can also trigger it manually from the Actions tab.

## Local Development

```bash
pip install requests beautifulsoup4
python scrape_events.py --verbose --output events.json
```

## Output Shape
The `events.json` matches PhillyHub's exact data shape:
```json
{
  "version": 1,
  "scraped_at": "2026-03-25T10:00:00-04:00",
  "event_count": 42,
  "events": [
    {
      "id": "ev_a1b2c3d4",
      "title": "FIFA: Brazil vs Haiti",
      "date": "2026-06-19",
      "time": "9:00 PM",
      "venue": "Philadelphia Stadium",
      "lat": 39.906,
      "lng": -75.168,
      "cat": "fifa",
      "free": false,
      "description": "Group C. At Philadelphia Stadium. BSL to NRG Station.",
      "source": "phillyfwc26.com",
      "ticketUrl": "https://www.fifa.com/tickets"
    }
  ]
}
```

## App Integration
Drop `useRemoteEvents.js` into your PhillyHub `src/` folder:
```jsx
import { useRemoteEvents } from './useRemoteEvents';

// In your component:
const { events, loading, source, lastUpdated } = useRemoteEvents(BUNDLED_EVENTS);
// events = live data (or bundled fallback)
// source = "remote" | "cache" | "bundled"
```

## Files
- `scrape_events.py` — The scraper (Python 3.12+)
- `useRemoteEvents.js` — React hook for the app
- `.github/workflows/scrape-events.yml` — GitHub Action
- `events.json` — Output (auto-generated)
- `README.md` — This file
