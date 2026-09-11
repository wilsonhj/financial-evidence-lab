import { readFileSync, existsSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import { SCHEMA_REFERENCE_ALIASES } from "./src/index";

const here = dirname(fileURLToPath(import.meta.url));
const load = (path: string) => JSON.parse(readFileSync(join(here, path), "utf8"));
const names = [
  "extraction-review-command",
  "extraction-review-result",
  "extraction-conflict",
  "extraction-validation-context",
  "extraction-event-page",
];

describe("ADR-0024 review contract", () => {
  it.each(names)("publishes %s as an individually versioned closed schema", (name) => {
    const path = `schemas/${name}.schema.json`;
    expect(existsSync(join(here, path))).toBe(true);
    const schema = load(path);
    expect(schema["x-fel-version"]).toBe("1.0.0");
    expect(schema.$id).toBe(`https://contracts.fel.dev/schemas/${name}/v1`);
    expect(schema.additionalProperties).toBe(false);
  });
  it("accepts explicit actions and rejects malformed or unbounded commands", () => {
    expect(existsSync(join(here, "fixtures/extraction-review-cases.valid.json"))).toBe(true);
    const ajv = new Ajv2020({ strict: false, allErrors: true });
    addFormats(ajv);
    for (const file of readdirSync(join(here, "schemas"))) {
      if (file.endsWith(".schema.json")) ajv.addSchema(load(`schemas/${file}`));
    }

    // The exported aliases are part of the consumer contract, not a test-only resolver.
    for (const [alias, target] of Object.entries(SCHEMA_REFERENCE_ALIASES)) {
      ajv.addSchema({ $id: alias, $ref: target });
    }

    const validate = ajv.getSchema(
      "https://contracts.fel.dev/schemas/extraction-review-command/v1",
    )!;
    for (const entry of load("fixtures/extraction-review-cases.valid.json")) {
      expect(validate(entry.command), `${entry.name}: ${JSON.stringify(validate.errors)}`).toBe(
        true,
      );
    }
    for (const entry of load("fixtures/extraction-review-cases.invalid.json")) {
      expect(validate(entry.command), entry.name).toBe(false);
    }
  });
});
