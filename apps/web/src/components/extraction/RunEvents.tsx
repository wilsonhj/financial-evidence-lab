"use client";
import { useEffect, useRef, useState } from "react";
import type { Event } from "../../lib/extraction/contracts";
import { consumeExtractionEvents } from "../../lib/extraction/sse";

export function RunEvents({ runId }: { runId: string }) {
  const [events, setEvents] = useState<Event[]>([]);
  const [status, setStatus] = useState("Connecting");
  const [attempt, setAttempt] = useState(0);
  const lastId = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    void consumeExtractionEvents(runId, {
      signal: controller.signal,
      lastId: lastId.current,
      onEvent(event) {
        lastId.current = event.id;
        if (event.type !== "heartbeat") {
          setEvents((previous) => [...previous, event].slice(-500));
          setStatus(event.type);
        }
      },
      onStatus: setStatus,
    }).catch(() => {
      if (!controller.signal.aborted)
        setStatus("Stream disconnected. Reconnect explicitly to resume from the last event.");
    });
    return () => controller.abort();
  }, [runId, attempt]);
  return (
    <section aria-label="Live extraction events">
      <h2>Live events</h2>
      <p role="status" aria-live="polite">
        {status}
      </p>
      <p>Retains the newest 500 events in this view. Waiting for review keeps the stream open.</p>
      <button type="button" onClick={() => setAttempt((a) => a + 1)}>
        Reconnect live events
      </button>
      <table>
        <caption>Ordered event history</caption>
        <thead>
          <tr>
            <th>Event ID</th>
            <th>Event</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td>{e.id}</td>
              <td>{e.type}</td>
              <td>
                <time dateTime={e.occurred_at}>{e.occurred_at}</time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
