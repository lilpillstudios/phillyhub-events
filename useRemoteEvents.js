/**
 * useRemoteEvents.js
 * PhillyHub — Live Event Data Fetch Hook
 * Lil Pill Studios © 2026
 *
 * Fetches fresh events.json from the hosted GitHub raw URL.
 * Falls back to bundled EVENTS array if fetch fails (offline, error, timeout).
 *
 * Usage in App:
 *   import { useRemoteEvents } from './useRemoteEvents';
 *   const { events, loading, source, lastUpdated, error } = useRemoteEvents(BUNDLED_EVENTS);
 *
 * Configure EVENTS_URL to point to your raw GitHub file:
 *   https://raw.githubusercontent.com/YOUR_USERNAME/phillyhub-events/main/events.json
 */

// ─── Configuration ───────────────────────────────────────────────────
// Replace with your actual GitHub raw URL after pushing the scraper repo
const EVENTS_URL = "https://raw.githubusercontent.com/YOUR_USERNAME/phillyhub-events/main/events.json";

// Cache key for localStorage
const CACHE_KEY = "ph_events_cache";
const CACHE_TTL = 1000 * 60 * 60 * 4; // 4 hours — don't hammer GitHub

// ─── Hook ────────────────────────────────────────────────────────────
import { useState, useEffect } from "react";

export function useRemoteEvents(bundledEvents) {
  const [events, setEvents] = useState(bundledEvents);
  const [loading, setLoading] = useState(true);
  const [source, setSource] = useState("bundled");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchEvents() {
      // 1. Check localStorage cache first
      try {
        const cached = localStorage.getItem(CACHE_KEY);
        if (cached) {
          const parsed = JSON.parse(cached);
          const age = Date.now() - (parsed._cachedAt || 0);
          if (age < CACHE_TTL && parsed.events?.length > 0) {
            if (!cancelled) {
              setEvents(parsed.events);
              setSource("cache");
              setLastUpdated(parsed.scraped_at);
              setLoading(false);
            }
            // Still try to fetch fresh in background, but don't block
            fetchFresh(parsed.events);
            return;
          }
        }
      } catch (e) {
        // Cache read failed — continue to fetch
      }

      // 2. No valid cache — fetch fresh
      await fetchFresh(bundledEvents);
    }

    async function fetchFresh(fallbackEvents) {
      try {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 8000); // 8s timeout

        const resp = await fetch(EVENTS_URL, {
          signal: controller.signal,
          cache: "no-cache",
        });
        clearTimeout(timeout);

        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const data = await resp.json();

        if (data.events && data.events.length > 0) {
          // Validate shape — make sure events have required fields
          const valid = data.events.filter(
            (e) => e.id && e.title && e.date && e.lat && e.lng
          );

          if (valid.length > 0 && !cancelled) {
            setEvents(valid);
            setSource("remote");
            setLastUpdated(data.scraped_at);
            setLoading(false);

            // Cache for next time
            try {
              localStorage.setItem(
                CACHE_KEY,
                JSON.stringify({ ...data, _cachedAt: Date.now() })
              );
            } catch (e) {
              // Storage full or unavailable — ok
            }
            return;
          }
        }

        throw new Error("No valid events in response");
      } catch (e) {
        if (!cancelled) {
          setError(e.message);
          // Fall back to whatever we have (cache or bundled)
          if (events === bundledEvents) {
            setEvents(fallbackEvents);
          }
          setSource(events === bundledEvents ? "bundled" : "cache");
          setLoading(false);
        }
      }
    }

    fetchEvents();

    return () => {
      cancelled = true;
    };
  }, []); // Run once on mount

  return { events, loading, source, lastUpdated, error };
}
