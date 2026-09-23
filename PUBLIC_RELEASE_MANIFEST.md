# Public release candidate manifest

- Product: Chatbot Student Advisor
- Source commit: `685c8f16dc29149e71cc4c6f8ec57ca8caea58f4`
- Candidate date: 2026-09-23
- License posture: all rights reserved
- Pilot context: UTT; the product is institution-neutral

## Included

- Backend, frontend, migrations, contracts and shared package
- ML/RAG source, notebooks, public demo corpus and evaluation code
- HTTT pilot catalog, sample CSV and owner-approved demo career mapping
- Docker/operations scripts, CI and release security workflow
- Sanitized public documentation and configuration templates

## Excluded

- Populated `.env` files and secrets
- Live database, user records, uploaded PDF/DOCX and scan files
- Vectorstore/index state and model binaries
- Agent instructions, prompts, private audit logs and planning history
- Private Git history

Runtime data can be ingested through the administrator document workflow; its
absence from Git does not remove the corresponding application functionality.

## Candidate verification

- API image: `sha256:6d652936cd5e78181c5225fad9d76f1adacdd068bdcf365ccf084f921947152a`
- Web image: `sha256:d9b7f6248b3ab996ec3bacbbb431edae0d8d46aac385947acc9f8e0d03bb6046`
- API Docker build: PASS
- Frontend card tests and Vite build: PASS
- Isolated migrations, 31 application integration checks and unit discovery: PASS
- Worktree safety sandbox: PASS
- Intentional unit-test skips: repeated-course fixture absent; approved model binary absent

GitHub secret scan, dependency audit and release-verification remain mandatory
after this candidate is initialized as the public repository.
