import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import openapiTS, { type SchemaObject } from "openapi-typescript";
import { beforeAll, describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const load = (path: string) => JSON.parse(readFileSync(join(here, path), "utf8"));
const version = "extraction-candidate-fields/v1";
const cases = load("fixtures/extraction-candidate-cases.valid.json") as Array<{
  name: string;
  fields: Record<string, string>;
}>;

// Bundle through the same installed public API used for generated types. Strip
// external $ids after bundling: its rewritten refs now address document components.
async function validators(path: string) {
  const schemas: Record<string, SchemaObject> = {};
  await openapiTS(pathToFileURL(path), {
    transform(schema, options) {
      if (/^#\/components\/schemas\/[^/]+$/.test(options.path ?? "")) {
        schemas[options.path!.split("/").at(-1)!] = schema;
      }
    },
  });
  const bundled = JSON.parse(
    JSON.stringify(schemas, (key, value) => (key === "$id" ? undefined : value)),
  );
  const ajv = new Ajv2020({ strict: false, allErrors: true });
  addFormats(ajv);
  return (name: string) =>
    ajv.compile({ components: { schemas: bundled }, $ref: `#/components/schemas/${name}` });
}

describe("read-only extraction candidates (ADR-0024 Amendment 1)", () => {
  let validate: Awaited<ReturnType<typeof validators>>;
  let reference: Awaited<ReturnType<typeof validators>>;
  beforeAll(async () => {
    validate = await validators(join(here, "openapi/openapi.yaml"));
    reference = await validators(
      join(here, "../../specs/003-agentic-extraction/contracts/extraction-api.yaml"),
    );
  });

  it.each(cases)("reads $name as text without requiring evidence", ({ fields }) => {
    const proposal = {
      ...load("fixtures/extraction-proposal.json"),
      payload: { schema_version: version, fields },
    };
    for (const contract of [validate, reference]) {
      const accepts = contract("ExtractionProposal");
      expect(accepts(proposal), JSON.stringify(accepts.errors)).toBe(true);
    }
  });

  it("accepts the ordinary strict payload shape without adding a wrapper", () => {
    const variants = load("fixtures/extraction-payloads.valid.json");
    for (const [name, payload] of Object.entries(variants)) {
      if (name === "note") continue;
      const proposal = { ...load("fixtures/extraction-proposal.json"), payload };
      expect(validate("ExtractionProposal")(proposal), name).toBe(true);
    }
  });

  it("rejects malformed wrapper structure, raw JSON values and non-public keys", () => {
    const fixture = load("fixtures/extraction-proposal.json");
    const invalid = [
      {},
      null,
      "candidate",
      [],
      { schema_version: version },
      { fields: {} },
      { schema_version: "extraction-candidate-fields/v2", fields: {} },
      { schema_version: version, fields: null },
      { schema_version: version, fields: "value" },
      { schema_version: version, fields: [] },
      { schema_version: version, fields: {}, state: "approved" },
      ...[null, 17, true, [], {}, { nested: "text" }].map((value) => ({
        schema_version: version,
        fields: { value },
      })),
      ...[
        "unknown",
        "_normalizer_blockers",
        "validation_summary",
        "evidence",
        "prompt",
        "__proto__",
      ].map((key) => ({ schema_version: version, fields: { [key]: "null" } })),
    ];
    for (const payload of invalid) {
      for (const contract of [validate, reference]) {
        expect(
          contract("ExtractionProposal")({ ...fixture, payload }),
          JSON.stringify(payload),
        ).toBe(false);
      }
    }
    const missing = { ...fixture };
    delete missing.payload;
    expect(validate("ExtractionProposal")(missing)).toBe(false);
  });

  it("bounds each field without silently truncating it", () => {
    const proposal = load("fixtures/extraction-proposal.json");
    for (const [length, accepted] of [
      [65536, true],
      [65537, false],
    ] as const) {
      // A JSON string's quote characters are part of its representation length.
      proposal.payload.fields = { description: `"${"x".repeat(length - 2)}"` };
      expect(validate("ExtractionProposal")(proposal)).toBe(accepted);
      expect(reference("ExtractionProposal")(proposal)).toBe(accepted);
    }
  });

  it("keeps strict approved payloads, edits and corrections closed to wrappers", () => {
    const proposal = load("fixtures/extraction-proposal.json");
    const strict = load("fixtures/extraction-payload.json");
    const edge = {
      source_span_id: "00000000-0000-4000-8000-000000000003",
      document_version_id: "00000000-0000-4000-8000-000000000004",
      role: "supports",
      citation_status: "verified",
    };
    const approved = {
      record_id: proposal.id,
      version_id: proposal.id,
      version: 1,
      kind: "kpi",
      metric_id: "arr",
      payload: strict,
      evidence: [edge],
      evidence_manifest_hash: `sha256:${"a".repeat(64)}`,
      ontology_version: "saas-metrics/v1",
      approved_by: proposal.id,
      created_at: "2026-09-11T00:00:00Z",
      approval_reason: "Reviewed source",
      normalizer_version: "normalize/v2",
      validator_version: "validate/v1",
      validation_context: null,
    };
    const correction = { reason: "Reviewed replacement", payload: strict, evidence: [edge] };
    const edit = {
      ...load("fixtures/extraction-review-command.json"),
      action: "edit",
      patch: [{ extraction_id: proposal.id, payload: strict, evidence: [edge] }],
    };
    for (const contract of [validate, reference]) {
      expect(contract("ApprovedExtraction")(approved)).toBe(true);
      expect(contract("CorrectionCommand")(correction)).toBe(true);
      expect(contract("ReviewCommand")(edit)).toBe(true);
      for (const { fields } of cases) {
        const wrapper = { schema_version: version, fields };
        expect(contract("ExtractionPayload")(wrapper)).toBe(false);
        expect(contract("ApprovedExtraction")({ ...approved, payload: wrapper })).toBe(false);
        expect(contract("CorrectionCommand")({ ...correction, payload: wrapper })).toBe(false);
        expect(
          contract("ReviewCommand")({
            ...edit,
            patch: [{ extraction_id: proposal.id, payload: wrapper, evidence: [edge] }],
          }),
        ).toBe(false);
      }
      expect(contract("ApprovedExtraction")({ ...approved, evidence: [] })).toBe(false);
      expect(contract("CorrectionCommand")({ ...correction, evidence: [] })).toBe(false);
      expect(
        contract("ReviewCommand")({
          ...edit,
          patch: [{ extraction_id: proposal.id, payload: strict, evidence: [] }],
        }),
      ).toBe(false);
    }
  });
});
