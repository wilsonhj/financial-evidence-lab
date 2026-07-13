import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const load = (rel: string) => JSON.parse(readFileSync(join(here, rel), "utf8"));

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);

const schemaFiles = readdirSync(join(here, "schemas")).filter((f) => f.endsWith(".schema.json"));

describe("contract schemas", () => {
  it("every schema compiles and has a versioned $id", () => {
    for (const file of schemaFiles) {
      const schema = load(`schemas/${file}`);
      expect(schema.$id, file).toMatch(/^https:\/\/contracts\.fel\.dev\/schemas\/[a-z-]+\/v\d+$/);
      expect(schema["x-fel-version"], file).toMatch(/^\d+\.\d+\.\d+$/);
      expect(() => ajv.compile(schema), file).not.toThrow();
    }
  });

  it("every fixture validates against its schema", () => {
    for (const file of schemaFiles) {
      const name = file.replace(".schema.json", "");
      const validate = ajv.getSchema(`https://contracts.fel.dev/schemas/${name}/v1`);
      expect(validate, name).toBeDefined();
      const fixture = load(`fixtures/${name}.json`);
      const ok = validate!(fixture);
      expect(ok, `${name}: ${JSON.stringify(validate!.errors)}`).toBe(true);
    }
  });

  it("claim status and citation entailment are the closed spec sets", () => {
    const claim = load("schemas/claim.schema.json");
    expect(claim.properties.status.enum).toEqual([
      "supported",
      "partially_supported",
      "contradicted",
      "derived",
      "unsupported",
    ]);
    const citation = load("schemas/citation.schema.json");
    expect(citation.properties.entailment.enum).toEqual([
      "entailed",
      "partial",
      "contradictory",
      "irrelevant",
    ]);
  });

  it("monetary values are decimal strings, never floats", () => {
    const fact = load("schemas/financial-fact.schema.json");
    expect(fact.properties.value.type).toBe("string");
    const validate = ajv.getSchema(SCHEMA("financial-fact"));
    const bad = { ...load("fixtures/financial-fact.json"), value: 1250000000 };
    expect(validate!(bad)).toBe(false);
  });

  it("job terminal states are exactly succeeded/failed/cancelled", () => {
    const job = load("schemas/job-envelope.schema.json");
    const states: string[] = job.properties.status.enum;
    expect(states).toEqual(["queued", "claimed", "running", "succeeded", "failed", "cancelled"]);
  });
});

function SCHEMA(name: string): string {
  return `https://contracts.fel.dev/schemas/${name}/v1`;
}
