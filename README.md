# AI School Parent Communication Assistant — RAG MVP

Standalone fictional-school demo for parent questions and school staff. Example school: **Sunrise Valley School**. All facts and names are illustrative.

## Features
- Parent chat with source attribution and staff escalation for unknown questions
- School admin can add/delete approved FAQ entries
- Admin-only upload/list/delete for school documents: PDF, DOCX, TXT, Markdown; 5 MB upload limit
- Document text chunking and local semantic vector retrieval using **ChromaDB + Sentence Transformers**
- Optional local answer generation through **Ollama**; without Ollama, the app returns retrieved excerpts (extractive RAG)
- Keyword FAQ fallback when optional vector dependencies are not installed
- SQLite storage and CI tests

## Run basic mode

Requires Python 3.10+.

```bash
python -m venv .venv
# Activate the environment for your operating system
pip install -r requirements.txt
# Configure SCHOOL_ADMIN_KEY to a long random secret
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. The chat works with sample FAQs. The admin dashboard requires the configured key for changes.

## Enable local RAG vector search

Install the optional dependencies:

```bash
pip install -r requirements-rag.txt
```

The first run downloads the Sentence Transformers embedding model. Vector data persists locally under `./chroma_data` by default. Set `RAG_VECTOR_PATH` to change that directory, and `RAG_EMBEDDING_MODEL` to choose another compatible embedding model.

Upload approved school policy documents in the admin dashboard. Supported file types are PDF, DOCX, TXT and Markdown. PDFs must contain extractable text; scanned PDFs need OCR, which this MVP does not include. Uploaded text and extracted document content are stored in SQLite. Do not upload confidential student records.

## Optional local answer generation

Vector search retrieves the relevant passages. To have a local language model compose a concise answer grounded in those passages, install Ollama separately, pull a model you can run on your computer, and set:

```bash
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
```

If Ollama is not configured or fails, the app transparently returns retrieved excerpts instead of pretending a language model answered. This keeps the MVP usable without OpenAI API keys or hosted model charges. Local models still require disk space, memory and CPU/GPU resources.

## Verify

```bash
python -m pytest -q
```

`GET /api/health` reports whether vector search dependencies are available. The CI job installs the lightweight base requirements, so it tests upload, permissions, fallback behavior and endpoints without downloading the embedding model.

## Policy management (versioned approvals)

The admin dashboard now includes **Policy versions**. Upload a policy PDF/DOCX/TXT/MD with a stable key (for example `fee-policy`), a title, and a YYYY-MM-DD effective date. Every upload creates a new **draft** version. An administrator must approve or reject it; rejected versions stay in the history but are not searchable. Approved future versions become applicable on their effective date; the system rechecks the date when parents ask questions and rebuilds the vector index when the day changes. The latest *effective, approved* version of each policy key is indexed. Version history is retained in SQLite.

API: `POST /api/policies` (multipart, admin), `GET /api/policies` (admin), `POST /api/policies/{id}/review` (admin JSON `{\"approve\":true}`), `GET /api/policies/active` (public metadata).

**MVP caveats:** The shared admin key is not separate reviewer identity or two-person approval. Legacy FAQs and unversioned documents remain searchable and may conflict with policies until migrated. Changes are reindexed across the whole knowledge collection rather than incrementally. Date-based activation follows the server's local calendar date, so configure the server to the school's timezone. Automatic parent notifications and tamper-evident audit logs are not implemented.

## Important limitations

**Prototype only; do not deploy publicly or use with real student data.** This MVP does not have a production staff identity system, parent verification, tenant isolation, rate limiting, robust audit controls, OCR, or school-grade data governance. The admin key is a shared secret, not individual staff authentication. RAG can retrieve irrelevant passages; the similarity threshold and escalation path reduce but do not eliminate errors. Staff must verify answers about fees, dates, health, safety and school policies.

## Next steps
1. Run the CI workflow and review the pull request.
2. Try approved fictional documents and tune retrieval quality.
3. Add secure staff accounts, document versioning and source-level access control.
4. Validate privacy/security and school needs before any real pilot.


## Feature 5: Potential policy conflicts and knowledge management

When approving a policy, the server scans active FAQ topics and unversioned document titles for exact normalized matches against the policy title or key. Any matches are **potential overlaps**, not proof of contradictory content. Approval is blocked until the administrator deactivates each flagged legacy source. Deactivated knowledge is excluded from vector indexing and keyword fallback, but preserved in SQLite. The admin dashboard includes a conflict list and deactivation controls; the API exposes `GET /api/conflicts`, `POST /api/conflicts/scan/{policy_id}`, and `POST /api/conflicts/legacy/{faq|document}/{id}/deactivate` (admin key required). Reactivation is blocked when a current approved policy has the same topic.

**Limitations:** This first release uses exact topic/key matching, not comprehensive semantic contradiction detection. Different labels for the same subject can escape detection; an administrator must review content manually. No separate two-person reviewer roles or notification service are included. Existing overlapping legacy items are not automatically disabled during migration.


## Feature 6: Parent policy notifications (in-app MVP)

Parents can opt in using a nickname via `POST /api/notifications/subscribe`, receiving an opaque bearer token. The parent inbox `GET /api/notifications` requires `X-Notification-Token` and lists only approved policy versions whose effective date has arrived, with read/unread state. `POST /api/notifications/{policy_id}/read` records a read receipt; `DELETE /api/notifications/subscription` unsubscribes and deletes the subscription/read receipts. Admins can see aggregate counts via `GET /api/notifications/admin/summary` using `X-Admin-Key`.

**Scope and limitations:** This is a free in-app inbox, not automatic push, SMS, email or WhatsApp delivery. Parents must open the app and select Check updates. The demo UI keeps the token only in the current tab, so a refresh requires a new subscription; use a secure parent identity/login system before production. It does not collect contact details or link subscribers to real children. Notifications display policy metadata, not unapproved policy text. Future-dated approvals become visible once effective, without a background scheduler.
