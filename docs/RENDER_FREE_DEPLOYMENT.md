# Deploy the fictional School Parent Assistant demo on Render Free

> **Demo only.** Do not upload actual school policies, student records, real parent identities, or other personal data. The current authentication, admin key and chat endpoints are not production hardened.

## What this deploys

- One Python/FastAPI web service using `render.yaml`, with the free Render instance.
- **Public demo mode** (`SCHOOL_DEMO_MODE=1`): fictional Sunrise Valley content is loaded automatically, the staff portal is read-only, and visitor questions are never stored.
- **Semantic search** with ChromaDB's ONNX build of `all-MiniLM-L6-v2` (`requirements-demo.txt`, `RAG_EMBEDDER=onnx`). No PyTorch, so it fits the free instance's memory (about 300–370 MB in local tests). Ollama is not installed, so answers quote the most relevant sentences.
- SQLite at `/tmp/school-demo.db`, which is **ephemeral**. All accounts, tickets, policies and uploads may disappear on restart, redeploy or spin-down. Do not treat it as persistent storage.
- An automatically generated `SCHOOL_ADMIN_KEY`. In demo mode it is shown on the staff unlock screen on purpose, because every staff change is blocked.
- Publicly accessible demo UI and API, with fictional data only.

## One-time deployment

1. Sign in to [Render](https://dashboard.render.com/) and connect your GitHub account, granting access to the private `rajuerladinny/ai-school-parent-assistant` repository. This authorization requires your action.
2. Open **New → Blueprint**, select the repository and the `main` branch (after this deployment PR is merged).
3. Render reads `render.yaml`. Review the service name, `free` plan, generated `SCHOOL_ADMIN_KEY`, and click **Apply/Deploy**. If Render's UI shows a paid plan, do not confirm it; check the plan selection and your account eligibility.
4. Wait for the deploy to succeed. Open the generated `https://...onrender.com` URL; the sample school UI should load.
5. Open `https://YOUR-SERVICE.onrender.com/api/health` and verify `status: ok`, `vector_search_enabled: true` and `demo_mode: true`.
6. Open the **Staff portal** and click **Use demo key**. Confirm that changes show the read-only message.
7. Test the sample question “What are school timings?” and a made-up unanswered question. Test parent accounts with invented usernames/passwords only.

## Free tier trade-offs

Render free services may spin down after inactivity and take time to wake up. Free instance availability, limits and pricing may change; verify Render's current pricing before enabling the service. The free filesystem is ephemeral. Database changes **will not reliably survive** restarts/redeploys, and multiple instances would not share SQLite data. The ONNX embedding model loads at startup; if the instance is restarted it is downloaded again if Render did not keep the build cache. The public app is not suitable for real school users.

## Before a real pilot

Use a managed persistent database (e.g. PostgreSQL), secure staff/parent identity and password reset, rate limiting, HTTPS-only security policies, data retention/deletion controls, backup strategy, school/guardian authorization, and production observability. Remove the legacy anonymous notification endpoints. Revisit RAG hosting separately: model weights and Chroma persistence may exceed free-tier resources.

## Troubleshooting

- **Build failure**: confirm the repository includes `requirements.txt` and `render.yaml` at its root.
- **App fails to start**: check Render logs and ensure the start command binds to `0.0.0.0` and `$PORT`.
- **Admin request fails with 401**: verify the key in Render's Environment settings and use `X-Admin-Key` only for authorized admin actions.
- **Data vanished**: expected on the ephemeral free service. Recreate only fictional demo data.
- **First request is slow**: the free instance may be waking after inactivity.

Deployment is not initiated by committing this configuration; you must connect GitHub to Render and approve the Blueprint deployment.
