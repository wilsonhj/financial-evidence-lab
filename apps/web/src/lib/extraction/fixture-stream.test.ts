import { describe, expect, it } from "vitest";
import { initialFixture } from "./fixture";
import { fixtureStream } from "./fixture-stream";
import { parseExtractionEvents } from "./sse";
it("delivers later terminal events once and closes without a reentrant double-close", async () => {
  const state = initialFixture(),
    run = state.runs[0]!;
  const response = fixtureStream(state, run.id, 0);
  const events = parseExtractionEvents(response, run.id);
  expect((await events.next()).value?.type).toBe("review_waiting");
  const next = events.next();
  state.events.push({ ...state.events[0]!, id: 2, type: "run_succeeded" });
  expect((await next).value?.type).toBe("run_succeeded");
  expect((await events.next()).done).toBe(true);
  await new Promise((resolve) => setTimeout(resolve, 70));
});
describe("fixture stream lifecycle", () => {
  it("resumes after a known ID and releases its timer on abort", async () => {
    const state = initialFixture(),
      controller = new AbortController();
    const response = fixtureStream(state, state.runs[0]!.id, 1, controller.signal);
    const reader = response.body!.getReader();
    const next = reader.read();
    controller.abort();
    expect((await next).done).toBe(true);
  });
});
