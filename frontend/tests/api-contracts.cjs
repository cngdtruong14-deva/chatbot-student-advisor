/* Frontend-to-backend route gate. This validates only routes the UI calls. */
const fs = require('node:fs');
const path = require('node:path');

const schemaPath = process.argv[2] || path.join(__dirname, '../../backend/tests/openapi.snapshot.json');
const schema = JSON.parse(fs.readFileSync(schemaPath, 'utf8'));
const expected = [
  ['post', '/api/v1/auth/login'], ['post', '/api/v1/auth/refresh'],
  ['post', '/api/v1/auth/logout'], ['post', '/api/v1/auth/register'],
  ['post', '/api/v1/auth/recover'], ['get', '/api/v1/system/capabilities'],
  ['get', '/api/v1/catalog/semesters'], ['get', '/api/v1/catalog/curricula'],
  ['get', '/api/v1/students/me'],
  ['get', '/api/v1/students/{student_id}/academic-summary'],
  ['patch', '/api/v1/students/me/goal'], ['get', '/api/v1/advisor/students'],
  ['post', '/api/v1/academic/required-gpa'], ['post', '/api/v1/academic/self-reported/preview'],
  ['post', '/api/v1/academic/target-score'], ['post', '/api/v1/academic/simulations'],
  ['get', '/api/v1/recommendations/courses'], ['post', '/api/v1/chat/sessions'],
  ['get', '/api/v1/chat/sessions'], ['get', '/api/v1/chat/sessions/{session_id}/messages'],
  ['post', '/api/v1/chat/sessions/{session_id}/messages'],
  ['post', '/api/v1/chat/sessions/{session_id}/messages/{client_turn_id}/feedback'],
  ['get', '/api/v1/knowledge/chunks/{chunk_id}'],
  ['get', '/api/v1/account/profile'], ['put', '/api/v1/account/profile'],
  ['get', '/api/v1/account/transcript'], ['put', '/api/v1/account/transcript'],
  ['get', '/api/v1/account/academic-summary'], ['post', '/api/v1/account/required-gpa'],
  ['post', '/api/v1/account/simulations'], ['post', '/api/v1/account/target-score'],
  ['post', '/api/v1/admin/account-invites'],
  ['post', '/api/v1/admin/accounts/{user_id}/recovery'],
  ['get', '/api/v1/admin/accounts'], ['get', '/api/v1/admin/cohorts'],
  ['get', '/api/v1/admin/account-audit'],
  ['post', '/api/v1/admin/accounts/{user_id}/academic-profile'],
  ['get', '/api/v1/admin/advisor-assignments'], ['post', '/api/v1/admin/advisor-assignments'],
  ['delete', '/api/v1/admin/advisor-assignments/{advisor_user_id}/{student_id}'],
  ['get', '/api/v1/admin/documents'], ['post', '/api/v1/admin/documents'],
  ['post', '/api/v1/admin/documents/{version_id}/ingest'],
  ['post', '/api/v1/admin/documents/{version_id}/activate'],
  ['post', '/api/v1/admin/documents/extract'],
  ['get', '/api/v1/admin/imports/history'],
  ['get', '/api/v1/admin/imports/templates/{import_type}'],
  ['post', '/api/v1/admin/imports/{import_type}'],
  ['get', '/api/v1/research-cases'], ['get', '/api/v1/admin/research/dashboard'],
  ['post', '/api/v1/research-cases/{case_id}/predictions'],
  ['get', '/api/v1/predictions/{prediction_id}/explanation'],
];

const missing = expected.filter(([method, route]) => !schema.paths?.[route]?.[method]);
if (missing.length) {
  throw new Error('Frontend API contract drift:\n' + missing.map(([m, p]) => `- ${m.toUpperCase()} ${p}`).join('\n'));
}
for (const [method, route] of expected) {
  const operation = schema.paths[route][method];
  if (!operation.responses || !Object.keys(operation.responses).some(code => Number(code) >= 200 && Number(code) < 300)) {
    throw new Error(`${method.toUpperCase()} ${route} has no successful response contract`);
  }
}
console.log(`PASS: ${expected.length} frontend API operations exist in the reviewed OpenAPI contract.`);
