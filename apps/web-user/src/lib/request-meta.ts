import { createId } from './utils';

function flattenParts(parts: Array<unknown>): string[] {
  const output: string[] = [];

  for (const part of parts) {
    if (part === null || part === undefined) {
      continue;
    }

    if (Array.isArray(part)) {
      output.push(...flattenParts(part));
      continue;
    }

    output.push(String(part));
  }

  return output;
}

function normalizePart(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ');
}

function hashString(value: string): string {
  let hash = 5381;

  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 33) ^ value.charCodeAt(index);
  }

  return (hash >>> 0).toString(36);
}

export function createRequestId(scope = 'req'): string {
  return createId(scope);
}

export function createIdempotencyKey(scope: string, parts: Array<unknown>): string {
  const normalized = flattenParts(parts)
    .map(normalizePart)
    .filter(Boolean)
    .join('|');

  return `${scope}:${hashString(normalized || scope)}`;
}
