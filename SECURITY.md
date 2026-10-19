# Security Policy

## Project status

This is a development prototype. Do not deploy it publicly or use it with real student, parent, or staff records until production security acceptance is complete.

## Reporting vulnerabilities

Please do **not** disclose security vulnerabilities through public GitHub issues or pull requests.

Use GitHub's **Report a vulnerability** / private vulnerability reporting feature if enabled in the repository's Security tab. If that option is unavailable, contact the repository owner privately through an established channel. Never include real credentials or personal data in a report.

## Supported versions

No production release is supported yet. Security fixes are reviewed on the active development branch.

## Responsible disclosure

Provide reproduction steps using fictional data and describe the potential impact. Avoid accessing other users' information or conducting disruptive tests against any live deployment.

## Public repository readiness

Before changing repository visibility, review the entire Git history for credentials, keys, tokens, school records, uploads, backups, and sensitive operational configuration. A clean working tree and a `.gitignore` file do **not** remove sensitive content from past commits. Rotate any exposed secrets and remove sensitive history before publication.
