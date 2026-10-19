# Contributing to AI School Parent Assistant

Thank you for your interest in improving this educational prototype.

## Before contributing

- Do not submit real student, parent, school, or staff data, credentials, access tokens, or production configuration.
- Open an issue describing the problem or feature before substantial changes.
- Keep changes small, focused, and documented.
- Security vulnerabilities should **not** be posted in public issues; contact the repository maintainer privately through GitHub.

## Local development

1. Fork or clone the repository and create a feature branch.
2. Use Python 3.12 and install dependencies with `python -m pip install -r requirements.txt`.
3. Run `python -m pytest -q` locally before opening a pull request.
4. Add tests for bug fixes and security-sensitive changes.
5. For PostgreSQL changes, use a disposable test database and run the integration tests documented in the repository.

## Pull requests

Explain what changed, how it was tested, and any security or migration implications. Never commit `.env` files, local databases, uploaded documents, or generated credentials.

The project is **not approved for production use or real student data**. Publishing source code does not imply a production deployment or a security certification.

## License

The project uses the Apache License 2.0. See [LICENSE](LICENSE) for the license notice and the linked complete license terms.
