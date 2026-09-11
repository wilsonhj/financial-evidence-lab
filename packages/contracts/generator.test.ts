import openapiTS, { astToString } from "openapi-typescript";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import { extractionPayloadWireType, generateContractTypes } from "./generate";

const path = "#/components/schemas/extraction-payload.schema";
const parse = (text: string) => ts.createSourceFile("api.ts", text, ts.ScriptTarget.Latest, true);

function named(node: ts.Node, name: string): boolean {
  return (
    ts.isPropertySignature(node) &&
    (ts.isIdentifier(node.name) || ts.isStringLiteral(node.name)) &&
    node.name.text === name
  );
}

function payload(source: ts.SourceFile) {
  const components = source.statements.find(
    (node) => ts.isInterfaceDeclaration(node) && node.name.text === "components",
  );
  if (!components || !ts.isInterfaceDeclaration(components)) throw new Error("Missing components");
  const schemas = components.members.find((node) => named(node, "schemas"));
  if (
    !schemas ||
    !ts.isPropertySignature(schemas) ||
    !schemas.type ||
    !ts.isTypeLiteralNode(schemas.type)
  )
    throw new Error("Missing schemas");
  const member = schemas.type.members.find((node) => named(node, "extraction-payload.schema"));
  if (!member || !ts.isPropertySignature(member) || !member.type)
    throw new Error("Missing payload");
  return { member, type: member.type };
}

// Compare syntax structure and literal values, independently of formatting,
// comments, source offsets, or the production hook's matching implementation.
function canonical(node: ts.Node, omitted?: ts.Node): unknown {
  const children: unknown[] = [];
  ts.forEachChild(node, (child) => {
    if (child !== omitted) children.push(canonical(child, omitted));
  });
  const text =
    ts.isIdentifier(node) || ts.isStringLiteral(node) || ts.isNumericLiteral(node)
      ? node.text
      : undefined;
  return { kind: node.kind, text, children };
}

describe("ExtractionPayload generation boundary", () => {
  it("removes only metadata and retains the exact seven-member union and every unrelated type", async () => {
    const original = parse(
      astToString(await openapiTS(new URL("./openapi/openapi.yaml", import.meta.url))),
    );
    const generated = parse(await generateContractTypes());
    const before = payload(original),
      after = payload(generated);
    if (!ts.isIntersectionTypeNode(before.type)) throw new Error("Expected original intersection");
    const variantMember = before.type.types[1];
    if (
      !variantMember ||
      !ts.isParenthesizedTypeNode(variantMember) ||
      !ts.isUnionTypeNode(variantMember.type)
    )
      throw new Error("Expected original variants");
    expect(variantMember.type.types).toHaveLength(7);
    expect(canonical(after.type)).toEqual(canonical(variantMember.type));
    expect(canonical(generated, after.member)).toEqual(canonical(original, before.member));
  });

  it("fails explicitly on upstream AST drift without stripping unrelated properties", async () => {
    const original = parse(
      astToString(await openapiTS(new URL("./openapi/openapi.yaml", import.meta.url))),
    );
    const { type } = payload(original);
    if (!ts.isIntersectionTypeNode(type)) throw new Error("Expected original intersection");
    const metadata = type.types[0],
      variants = type.types[1];
    if (
      !metadata ||
      !ts.isTypeLiteralNode(metadata) ||
      !variants ||
      !ts.isParenthesizedTypeNode(variants) ||
      !ts.isUnionTypeNode(variants.type)
    )
      throw new Error("Expected original shape");
    const field = metadata.members[0];
    if (!field || !ts.isPropertySignature(field)) throw new Error("Expected metadata member");
    const changed = [
      variants,
      ts.factory.createIntersectionTypeNode([metadata, variants, metadata]),
      ts.factory.createIntersectionTypeNode([
        ts.factory.createTypeLiteralNode([
          ...metadata.members,
          ts.factory.createPropertySignature(
            undefined,
            "wire_field",
            undefined,
            ts.factory.createKeywordTypeNode(ts.SyntaxKind.StringKeyword),
          ),
        ]),
        variants,
      ]),
      ts.factory.createIntersectionTypeNode([
        ts.factory.createTypeLiteralNode([
          ts.factory.updatePropertySignature(
            field,
            field.modifiers,
            ts.factory.createIdentifier("runtime"),
            field.questionToken,
            field.type,
          ),
        ]),
        variants,
      ]),
      ts.factory.createIntersectionTypeNode([
        metadata,
        ts.factory.createParenthesizedType(
          ts.factory.createUnionTypeNode(variants.type.types.slice(1)),
        ),
      ]),
      ts.factory.createIntersectionTypeNode([
        metadata,
        ts.factory.createParenthesizedType(
          ts.factory.createUnionTypeNode([
            variants.type.types[1]!,
            ...variants.type.types.slice(1),
          ]),
        ),
      ]),
    ];
    for (const altered of changed)
      expect(() => extractionPayloadWireType(altered, { path })).toThrow("generator AST changed");
    expect(extractionPayloadWireType(type, { path: "#/components/schemas/Other" })).toBeUndefined();
  });
});
