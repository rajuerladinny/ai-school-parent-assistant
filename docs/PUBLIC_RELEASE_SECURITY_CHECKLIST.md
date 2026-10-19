# Public release security verification

**Status: NOT VERIFIED.** Repository visibility does not establish security or deployment readiness.

## Required local checks (on a trusted machine)

Clone the repository, then check out the branch being reviewed:

```bash
git clone https://github.com/rajuerladinny/ai-school-parent-assistant.git
cd ai-school-parent-assistant
git fetch origin
git switch feature/production-security-operations
```

### 1. Full-history secrets scan

Install Gitleaks from its official release and run:

```bash
gitleaks git --redact --exit-code 1 .
```

Run again on `main` if scanning only the PR branch is insufficient for the repository's full reachable history. Review GitHub secret-scanning alerts as well. If a real secret is found, revoke or rotate it immediately; deleting it from the latest commit is not sufficient.

### 2. Dependency audit

Use Python 3.12 in a clean virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-rag.txt pip-audit
python -m pip_audit
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`. Dependency ranges are not a lockfile: record the exact resolved package versions and audit results.

### 3. Runtime tests

```bash
python -m pytest -q
```

For PostgreSQL integration tests, use a disposable PostgreSQL 16 database and the documented bootstrap/integration workflow. Never point tests at production data.

## Acceptance checklist

- [ ] Full-history Gitleaks scan reviewed and passed
- [ ] GitHub secret-scanning alerts reviewed and resolved
- [ ] Base and optional RAG dependency audits passed or exceptions documented
- [ ] Python unit/integration tests passed
- [ ] PostgreSQL integration and backup/restore tests passed
- [ ] Production identity, TLS, monitoring, and rate-limit acceptance documented
- [ ] Main-branch protection enforcement verified
- [ ] Complete official Apache-2.0 license text added

**No deployment or PR merge until the appropriate acceptance criteria are met.**
