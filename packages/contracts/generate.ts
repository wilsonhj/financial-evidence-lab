/** ADR-0024 Amendment 1: wire types must not require JSON Schema metadata. */
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import openapiTS, {
  astToString,
  COMMENT_HEADER,
  type TransformNodeOptions,
} from "openapi-typescript";
import { format, resolveConfig } from "prettier";
import ts from "typescript";

const payloadPath = "#/components/schemas/extraction-payload.schema";
const variants = [
  "kpi",
  "guidancePoint",
  "guidanceRange",
  "guidanceFloor",
  "guidanceCeiling",
  "guidanceQualitative",
  "revenueDriver",
];

function componentName(type: ts.TypeNode): string | undefined {
  if (
    !ts.isIndexedAccessTypeNode(type) ||
    !ts.isLiteralTypeNode(type.indexType) ||
    !ts.isStringLiteral(type.indexType.literal)
  )
    return;
  const schemas = type.objectType;
  if (
    !ts.isIndexedAccessTypeNode(schemas) ||
    !ts.isLiteralTypeNode(schemas.indexType) ||
    !ts.isStringLiteral(schemas.indexType.literal) ||
    schemas.indexType.literal.text !== "schemas" ||
    !ts.isTypeReferenceNode(schemas.objectType) ||
    schemas.objectType.typeArguments ||
    !ts.isIdentifier(schemas.objectType.typeName) ||
    schemas.objectType.typeName.text !== "components"
  )
    return;
  return type.indexType.literal.text;
}

/** Supported postTransform hook; remove only the known metadata intersection. */
export function extractionPayloadWireType(
  type: ts.TypeNode,
  { path }: Pick<TransformNodeOptions, "path">,
): ts.TypeNode | undefined {
  if (path !== payloadPath) return;
  const fail = () => {
    throw new Error("ExtractionPayload generator AST changed; review the metadata-only transform");
  };
  if (!ts.isIntersectionTypeNode(type) || type.types.length !== 2) return fail();
  const [metadata, parenthesized] = type.types;
  if (
    !metadata ||
    !ts.isTypeLiteralNode(metadata) ||
    metadata.members.length !== 1 ||
    !parenthesized ||
    !ts.isParenthesizedTypeNode(parenthesized) ||
    !ts.isUnionTypeNode(parenthesized.type)
  )
    return fail();
  const field = metadata.members[0];
  if (
    !field ||
    !ts.isPropertySignature(field) ||
    !ts.isIdentifier(field.name) ||
    field.name.text !== "$defs" ||
    field.questionToken ||
    !field.type ||
    !ts.isTypeLiteralNode(field.type)
  )
    return fail();
  const union = parenthesized.type;
  if (
    union.types.length !== variants.length ||
    union.types.some((member, index) => componentName(member) !== variants[index])
  )
    return fail();
  // Reuse the exact seven original union members: no wire fields or validators change.
  return union;
}

export async function generateContractTypes(): Promise<string> {
  let transformed = 0;
  const ast = await openapiTS(new URL("./openapi/openapi.yaml", import.meta.url), {
    postTransform(type, options) {
      const wire = extractionPayloadWireType(type, options);
      if (wire) transformed += 1;
      return wire;
    },
  });
  if (transformed !== 1)
    throw new Error("Expected exactly one bundled ExtractionPayload transform");
  const config = await resolveConfig(
    fileURLToPath(new URL("./src/generated/api.ts", import.meta.url)),
  );
  return format(COMMENT_HEADER + astToString(ast), { ...config, parser: "typescript" });
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  const argument = process.argv[2];
  if (process.argv.length > 3 || (argument !== undefined && argument !== "--check")) {
    throw new Error("Usage: node generate.ts [--check]");
  }
  const output = new URL("./src/generated/api.ts", import.meta.url);
  const generated = await generateContractTypes();
  if (argument === "--check") {
    if ((await readFile(output, "utf8")) !== generated)
      throw new Error("Generated contracts drift; run generate");
  } else {
    await writeFile(output, generated);
  }
}
