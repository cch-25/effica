import openapi from "@/lib/api/generated/openapi.json";
import type { components } from "@/lib/api/generated/schema";

type SchemaName = keyof components["schemas"];
type Schema = {
  $ref?: string;
  anyOf?: Schema[];
  type?: string;
  enum?: unknown[];
  const?: unknown;
  required?: string[];
  properties?: Record<string, Schema>;
  additionalProperties?: boolean | Schema;
  items?: Schema;
  minimum?: number;
  maximum?: number;
  pattern?: string;
};

const schemas = openapi.components.schemas as unknown as Record<string, Schema>;

function fail(path: string, message: string): never {
  throw new TypeError(`Mock response violates OpenAPI at ${path}: ${message}`);
}

function validate(schema: Schema, value: unknown, path: string): void {
  if (schema.$ref) {
    const name = schema.$ref.split("/").at(-1);
    const referenced = name ? schemas[name] : undefined;
    if (!referenced) fail(path, `unknown schema reference ${schema.$ref}`);
    validate(referenced, value, path);
    return;
  }
  if (schema.anyOf) {
    const valid = schema.anyOf.some((candidate) => {
      try {
        validate(candidate, value, path);
        return true;
      } catch {
        return false;
      }
    });
    if (!valid) fail(path, "does not match any allowed shape");
    return;
  }
  if (schema.const !== undefined && value !== schema.const) fail(path, `must equal ${String(schema.const)}`);
  if (schema.enum && !schema.enum.includes(value)) fail(path, `must be one of ${schema.enum.join(", ")}`);
  if (schema.type === "null") {
    if (value !== null) fail(path, "must be null");
    return;
  }
  if (schema.type === "string") {
    if (typeof value !== "string") fail(path, "must be a string");
    if (schema.pattern && !new RegExp(schema.pattern).test(value)) fail(path, `must match ${schema.pattern}`);
    return;
  }
  if (schema.type === "boolean") {
    if (typeof value !== "boolean") fail(path, "must be a boolean");
    return;
  }
  if (schema.type === "number" || schema.type === "integer") {
    if (typeof value !== "number" || !Number.isFinite(value)) fail(path, "must be a finite number");
    if (schema.type === "integer" && !Number.isInteger(value)) fail(path, "must be an integer");
    if (schema.minimum !== undefined && value < schema.minimum) fail(path, `must be >= ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum) fail(path, `must be <= ${schema.maximum}`);
    return;
  }
  if (schema.type === "array") {
    if (!Array.isArray(value)) fail(path, "must be an array");
    value.forEach((item, index) => schema.items && validate(schema.items, item, `${path}[${index}]`));
    return;
  }
  if (schema.type === "object" || schema.properties || schema.additionalProperties !== undefined) {
    if (typeof value !== "object" || value === null || Array.isArray(value)) fail(path, "must be an object");
    const record = value as Record<string, unknown>;
    for (const key of schema.required ?? []) {
      if (!(key in record)) fail(`${path}.${key}`, "is required");
    }
    for (const [key, item] of Object.entries(record)) {
      const property = schema.properties?.[key];
      if (property) validate(property, item, `${path}.${key}`);
      else if (schema.additionalProperties === false) fail(`${path}.${key}`, "is not allowed");
      else if (typeof schema.additionalProperties === "object") validate(schema.additionalProperties, item, `${path}.${key}`);
    }
  }
}

export function mockResponse<Name extends SchemaName>(
  schemaName: Name,
  value: components["schemas"][Name],
): components["schemas"][Name] {
  validate(schemas[schemaName], value, schemaName);
  return value;
}
