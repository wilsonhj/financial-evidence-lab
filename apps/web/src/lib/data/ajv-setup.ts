import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";

/**
 * The one Ajv2020 construction shared by every schema validator in this
 * package: `@fel/contracts` schemas are drafted against 2020-12 and use
 * `format` keywords (e.g. `date-time`, `uuid`), so every consumer needs the
 * same `Ajv2020` + `ajv-formats` setup. Centralized here so
 * `reader-contract-validator.ts` and `fixture.test.ts` do not each hand-roll
 * it (see the former TODO in `fixture.test.ts`).
 *
 * `packages/contracts/contracts.test.ts` has its own copy: that package is a
 * frozen contract boundary web must not import from for tooling, so the
 * duplication there is deliberate and out of scope for this module (a
 * contract-change issue would be needed to share a validator across the
 * package boundary).
 */
export function createAjv(): Ajv2020 {
  const ajv = new Ajv2020({ strict: false, allErrors: true });
  addFormats(ajv);
  return ajv;
}
