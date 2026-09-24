# Public release manifest

- Product: Chatbot Student Advisor
- Candidate date: 2026-09-24
- License posture: all rights reserved
- Pilot context: UTT; product architecture is institution-neutral

## Included

- Backend, frontend, migrations, contracts and shared package.
- ML/RAG source, governed notebooks, public `DEMO1.md` corpus and evaluation code.
- Synthetic Academic Demo v2 raw/normalized ZIPs with SHA-256 documentation.
- Public HTTT pilot catalog, sample CSV and owner-approved demo career mapping.
- Gemini HMAC gateway source and reusable Bicep infrastructure.
- Docker/operations scripts, CI/release-security workflow and sanitized docs.

## Excluded

- Populated `.env`, Key Vault values and every credential.
- Live database, user records, chat history and uploaded PDF/DOCX/scan files.
- Vectorstore/index state and model binaries.
- Generated Bicep JSON, local Azure deployment receipts and private cloud IDs.
- Agent instructions, prompts, private audit logs/plans and private Git history.

Runtime data can be ingested through the administrator workflow; excluding it
from Git does not remove the application feature.

## Required release evidence

The public release is acceptable only after the exact committed tree passes:

1. frontend tests and production build;
2. Python compilation and targeted gateway/runtime tests;
3. Docker/API isolated application verification where available;
4. GitHub `secret-scan`, `dependency-audit` and `release-verification` jobs.

Do not write PASS into this manifest before those commands have completed on the
current candidate commit.

## Local candidate evidence (2026-09-24)

- Dataset archives: 12 raw files, no account table, 1.000 students, 24.370
  enrollments, zero duplicate business keys; normalized manifests all matched.
- Frontend: 24 chat/sidebar assertions, 3 input assertions, 45 API contract
  assertions and Vite production build passed.
- Gateway/runtime/security targeted suite: 27 tests passed.
- API image unit discovery: 215 tests passed, 38 intentional fixture/artifact
  skips, no errors.
- API image: `sha256:34ee8a55240bc6e7602c768c54a4ac8a89c8eccb56bed03211bcdeb5c78ac57d`.
- Web image: `sha256:7a75792d37ee0df645ff34dcf5ecb439579dba40fd08321df88f0150adb8512d`.
- Gitleaks scanned the filtered staged snapshot: no leaks found.
- Both Bicep entry points compiled; only reviewed non-blocking API-type/linter
  warnings remain.
- GitHub jobs remain pending until this exact tree is committed and pushed.
