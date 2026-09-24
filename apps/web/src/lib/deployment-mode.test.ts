import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { assertDeploymentMode, type DeploymentEnvironment } from "./deployment-mode";
const id = "11111111-1111-4111-8111-111111111111";
const token = (role: unknown = "owner") =>
  `mock.${Buffer.from(JSON.stringify({ org_id: id, sub: id, role })).toString("base64url")}`;
const reader = {
  FEL_DEPLOYMENT_MODE: "reader-smoke",
  FEL_EVIDENCE_SOURCE: "http",
  FEL_AUTH_MODE: "mock",
  FEL_READER_SMOKE_TARGET: "test-reader",
  FEL_API_BASE_URL: "https://api.example.test",
  FEL_API_BEARER_TOKEN: token(),
};
const dirs: string[] = [];
afterEach(() => dirs.splice(0).forEach((dir) => rmSync(dir, { recursive: true, force: true })));
function synthetic() {
  const dir = mkdtempSync(join(tmpdir(), "fel-guard-"));
  dirs.push(dir);
  const path = join(dir, "manifest.json");
  const data = Object.fromEntries(
    [
      "org",
      "user",
      "workspace",
      "entity",
      "policy",
      "document",
      "version",
      "section",
      "span",
      "corpus",
    ].map((key) => [key, id]),
  );
  Object.assign(data, { schema_version: "extraction-cross-stack/v1", target: "unit-cross-stack" });
  const raw = JSON.stringify(
    Object.fromEntries(Object.entries(data).sort(([a], [b]) => a.localeCompare(b))),
  );
  writeFileSync(path, raw);
  return {
    path,
    raw,
    env: {
      ...reader,
      FEL_DEPLOYMENT_MODE: "synthetic-http",
      FEL_API_BASE_URL: "http://127.0.0.1:8211",
      FEL_ALLOW_MOCK_LLM: "1",
      FEL_SYNTHETIC_HTTP_TARGET: data.target,
      FEL_WORKSPACE_ID: id,
      FEL_ENTITY_IDS: id,
      CROSS_STACK_MANIFEST: path,
    },
  };
}
const denied = (env: DeploymentEnvironment) =>
  expect(() => assertDeploymentMode(env)).toThrow(/^PUBLIC_AUTH_NOT_READY$/);
describe("deployment gate", () => {
  it.each([undefined, "public", "", " public", "fixture ", "unknown"])(
    "refuses valid shared config in mode %s",
    (mode) => denied({ ...reader, FEL_DEPLOYMENT_MODE: mode }),
  );
  it("requires an offline fixture with no bearer", () => {
    denied({ FEL_EVIDENCE_SOURCE: "fixture" });
    denied({ FEL_DEPLOYMENT_MODE: "public", FEL_EVIDENCE_SOURCE: "fixture" });
    expect(
      assertDeploymentMode({ FEL_DEPLOYMENT_MODE: "fixture", FEL_EVIDENCE_SOURCE: "fixture" }),
    ).toBe("fixture");
    denied({
      FEL_DEPLOYMENT_MODE: "fixture",
      FEL_EVIDENCE_SOURCE: "fixture",
      FEL_API_BEARER_TOKEN: "secret",
    });
    denied({ ...reader, FEL_DEPLOYMENT_MODE: "fixture" });
  });
  it.each([["owner"], ["viewer"], null, 1, {}].map((role) => ({ role })))(
    "rejects a non-string mock role",
    ({ role }) => {
      denied({ ...reader, FEL_API_BEARER_TOKEN: token(role) });
    },
  );
  it("preserves explicit reader and denied-user/invalid smoke variants", () => {
    for (const bearer of [token(), token("viewer"), "invalid"])
      expect(assertDeploymentMode({ ...reader, FEL_API_BEARER_TOKEN: bearer })).toBe(
        "reader-smoke",
      );
  });
  it.each(["", "jwt.secret.signature", "mock.bad", "mock." + "x".repeat(8192), token("admin")])(
    "rejects a malformed/nonmock bearer",
    (bearer) => denied({ ...reader, FEL_API_BEARER_TOKEN: bearer }),
  );
  it.each([
    { FEL_AUTH_MODE: "supabase" },
    { FEL_READER_SMOKE_TARGET: " bad" },
    { FEL_EVIDENCE_SOURCE: "fixture" },
    { FEL_API_BASE_URL: "https://secret@api.test" },
    { FEL_API_BASE_URL: "https://api.test/?token=secret" },
  ])("rejects invalid reader proof", (patch) => denied({ ...reader, ...patch }));
  it("accepts exact synthetic bindings on all loopback hosts", () => {
    const { env } = synthetic();
    for (const host of ["localhost", "127.0.0.1", "[::1]"])
      expect(assertDeploymentMode({ ...env, FEL_API_BASE_URL: `http://${host}:8211` })).toBe(
        "synthetic-http",
      );
  });
  it.each([
    { FEL_API_BASE_URL: "http://api.test" },
    { FEL_ALLOW_MOCK_LLM: "true" },
    { FEL_SYNTHETIC_HTTP_TARGET: "other-target" },
    { FEL_WORKSPACE_ID: "22222222-2222-4222-8222-222222222222" },
    { FEL_ENTITY_IDS: `${id},${id}` },
    { FEL_API_BEARER_TOKEN: "invalid" },
    { FEL_API_BEARER_TOKEN: token("viewer") },
    { CROSS_STACK_MANIFEST: "/nonexistent/secret" },
  ])("rejects synthetic proof mismatch without diagnostics", (patch) =>
    denied({ ...synthetic().env, ...patch }),
  );
  it.each([
    "newline",
    "duplicate",
    "extra",
    "uppercase",
    "oversize",
    "invalid-utf8",
    "bom",
    "malformed",
  ])("rejects %s manifest", (variant) => {
    const { path, raw, env } = synthetic();
    const values: Record<string, string | Buffer> = {
      newline: raw + "\n",
      duplicate: raw.replace("{", `{"org":"${id}",`),
      extra: raw.replace("{", '{"extra":1,'),
      uppercase: raw.replace(id, "AAAAAAAA-1111-4111-8111-111111111111"),
      oversize: " ".repeat(16385),
      "invalid-utf8": Buffer.from([255]),
      bom: Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from(raw)]),
      malformed: "{",
    };
    writeFileSync(path, values[variant]!);
    denied(env);
  });
});
