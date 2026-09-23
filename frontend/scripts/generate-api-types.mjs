// No network/dependencies. Reviewed FastAPI snapshot is the single generator input.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const schema = JSON.parse(fs.readFileSync(path.join(root, '../backend/tests/openapi.snapshot.json'), 'utf8'));
const name = s => s.replace(/[^a-zA-Z0-9_]/g, '_');
function type(s) {
  if (!s || !Object.keys(s).length) return 'unknown';
  if (s.$ref) return name(s.$ref.split('/').at(-1));
  if ('const' in s) return JSON.stringify(s.const);
  if (s.enum) return s.enum.map(x => JSON.stringify(x)).join(' | ');
  if (s.anyOf || s.oneOf) return (s.anyOf || s.oneOf).map(type).join(' | ');
  if (s.allOf) return s.allOf.map(type).join(' & ');
  if (s.type === 'array') return `Array<${type(s.items)}>`;
  if (s.type === 'string') return 'string';
  if (s.type === 'number' || s.type === 'integer') return 'number';
  if (s.type === 'boolean') return 'boolean';
  if (s.type === 'null') return 'null';
  if (s.type === 'object' || s.properties) {
    const props = Object.entries(s.properties || {}).map(([k,v]) => `${JSON.stringify(k)}${(s.required || []).includes(k) ? '' : '?'}: ${type(v)};`).join(' ');
    const additional = s.additionalProperties === false ? '' : `[key: string]: ${typeof s.additionalProperties === 'object' ? type(s.additionalProperties) : 'unknown'};`;
    return `{ ${props} ${additional} }`;
  }
  return 'unknown';
}
const output = '// Generated from backend/tests/openapi.snapshot.json. Do not hand edit.\n' + Object.entries(schema.components.schemas).sort(([a],[b]) => a.localeCompare(b)).map(([key, value]) => `export type ${name(key)} = ${type(value)};`).join('\n') + '\n';
const target = path.join(root, 'src/generated-api.ts');
if (process.argv.includes('--stdout')) process.stdout.write(output);
else if (process.argv.includes('--write')) fs.writeFileSync(target, output, 'utf8');
else if (process.argv.includes('--check')) {
  if (fs.readFileSync(target, 'utf8') !== output) throw Error('API types drift: review snapshot and regenerate');
  console.log('PASS: generated API types match reviewed snapshot');
} else throw Error('Use --stdout to review, --write for an approved snapshot, or --check');
