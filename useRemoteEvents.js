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
 */

// ─── Configuration ───────────────────────────────────────────────────
const EVENTS_URL = "https://raw.githubusercontent.com/lilpillstudios/phillyhub-events/main/events.json";

// Cache key for localStorage
const CACHE_KEY = "ph_events_cache";
const CACHE_TTL = 1000 * 60 * 60 * 4; // 4 hours

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
        const timeout = setTimeout(() => controller.abort(), 8000);

        const resp = await fetch(EVENTS_URL, {
          signal: controller.signal,
          cache: "no-cache",
        });
        clearTimeout(timeout);

        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

        const data = await resp.json();

        if (data.events && data.events.length > 0) {
          const valid = data.events.filter(
            (e) => e.id && e.title && e.date && e.lat && e.lng
          );

          if (valid.length > 0 && !cancelled) {
            setEvents(valid);
            setSource("remote");
            setLastUpdated(data.scraped_at);
            setLoading(false);

            try {
              localStorage.setItem(
                CACHE_KEY,
                JSON.stringify({ ...data, _cachedAt: Date.now() })
              );
            } catch (e) {}
            return;
          }
        }

        throw new Error("No valid events in response");
      } catch (e) {
        if (!cancelled) {
          setError(e.message);
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
  }, []);

  return { events, loading, source, lastUpdated, error };
}
