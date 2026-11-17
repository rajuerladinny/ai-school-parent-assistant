# Deploy the fictional School Parent Assistant demo on Render Free

> **Demo only.** Do not upload actual school policies, student records, real parent identities, or other personal data. The current authentication, admin key and chat endpoints are not production hardened.

## What this deploys

- One Python/FastAPI web service using `render.yaml`, with the free Render instance.
- Lightweight requirements only: sample FAQ answers and keyword fallback. ChromaDB, Sentence Transformers, and Ollama are **not installed**.
- SQLite at `/tmp/school-demo.db`, which is **ephemeral**. All accounts, tickets, policies and uploads may disappear on restart, redeploy or spin-down. Do not treat it as persistent storage.
- An automatically generated `SCHOOL_ADMIN_KEY` kept in Render's environment settings. Never commit or paste the key into source control.
- Publicly accessible demo UI and API. Keep the admin key secret and avoid storing sensitive data.

## One-time deployment

1. Sign in to [Render](https://dashboard.render.com/) and connect your GitHub account, granting access to the private `rajuerladinny/ai-school-parent-assistant` repository. This authorization requires your action.
2. Open **New → Blueprint**, select the repository and the `main` branch (after this deployment PR is merged).
3. Render reads `render.yaml`. Review the service name, `free` plan, generated `SCHOOL_ADMIN_KEY`, and click **Apply/Deploy**. If Render's UI shows a paid plan, do not confirm it; check the plan selection and your account eligibility.
4. Wait for the deploy to succeed. Open the generated `https://...onrender.com` URL; the sample school UI should load.
5. Open `https://YOUR-SERVICE.onrender.com/api/health` and verify `status: ok`. `vector_search_enabled: false` is expected on the free lightweight deployment.
6. For admin testing, find `SCHOOL_ADMIN_KEY` in Render **Environment** and copy it only into the admin key field of your demo. Do not share it in chat, screenshots, logs, or public links.
7. Test the sample question “What are school timings?” and a made-up unanswered question. Test parent accounts with invented usernames/passwords only.

## Free tier trade-offs

Render free services may spin down after inactivity and take time to wake up. Free instance availability, limits and pricing may change; verify Render's current pricing before enabling the service. The free filesystem is ephemeral. Database changes **will not reliably survive** restarts/redeploys, and multiple instances would not share SQLite data. No vector model is loaded; the demo uses keyword FAQ fallback. The public app is not suitable for real school users.

## Before a real pilot

Use a managed persistent database (e.g. PostgreSQL), secure staff/parent identity and password reset, rate limiting, HTTPS-only security policies, data retention/deletion controls, backup strategy, school/guardian authorization, and production observability. Remove the legacy anonymous notification endpoints. Revisit RAG hosting separately: model weights and Chroma persistence may exceed free-tier resources.

## Troubleshooting

- **Build failure**: confirm the repository includes `requirements.txt` and `render.yaml` at its root.
- **App fails to start**: check Render logs and ensure the start command binds to `0.0.0.0` and `$PORT`.
- **Admin request fails with 401**: verify the key in Render's Environment settings and use `X-Admin-Key` only for authorized admin actions.
- **Data vanished**: expected on the ephemeral free service. Recreate only fictional demo data.
- **First request is slow**: the free instance may be waking after inactivity.

Deployment is not initiated by committing this configuration; you must connect GitHub to Render and approve the Blueprint deployment.
