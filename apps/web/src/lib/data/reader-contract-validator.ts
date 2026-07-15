import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";

import financialFactSchema from "@fel/contracts/schemas/financial-fact.schema.json";
import readerResponseSchema from "@fel/contracts/schemas/reader-response.schema.json";
import sourceSpanSchema from "@fel/contracts/schemas/source-span.schema.json";

type JsonSchema = Record<string, unknown>;

/**
 * `x-fel-open-enum` means consumers must accept future values even though the
 * current schema lists known values for documentation/code generation.
 */
function relaxOpenEnums(value: unknown): void {
  if (Array.isArray(value)) {
    for (const item of value) relaxOpenEnums(item);
    return;
  }
  if (typeof value !== "object" || value === null) return;
  const schema = value as JsonSchema;
  if (schema["x-fel-open-enum"] === true) delete schema.enum;
  for (const child of Object.values(schema)) relaxOpenEnums(child);
}

const readerSchema = structuredClone(readerResponseSchema) as JsonSchema;
relaxOpenEnums(readerSchema);

const ajv = new Ajv2020({ strict: false, allErrors: true });
addFormats(ajv);
ajv.addSchema(sourceSpanSchema);
ajv.addSchema(financialFactSchema);
const validate = ajv.compile(readerSchema);

/** Exact structural validation; errors are intentionally not exposed. */
export function matchesReaderResponseSchema(value: unknown): boolean {
  return validate(value) === true;
}
