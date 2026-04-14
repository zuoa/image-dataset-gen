# Repository Guidelines

## Project Structure & Module Organization

This monorepo contains three services:

- `backend/`: Flask REST API, SQLAlchemy models, service layer, and API tests in `backend/tests/`
- `frontend/`: React 18 + TypeScript + Vite app, with UI code under `frontend/src/`
- `annotator/`: Flask microservice for annotation, with tests in `annotator/tests/`
- `.github/workflows/`: CI workflow for frontend build and Docker image packaging
- `docker-compose.yml`: local multi-service orchestration

Keep changes scoped to the service you are editing. Shared operational behavior should be reflected in `README.md` and, when relevant, `docker-compose.yml`.

## Build, Test, and Development Commands

- `docker compose up --build`: build and run the full stack locally
- `cd frontend && npm ci && npm run build`: install frontend deps and produce a production build
- `cd backend && pip install -r requirements.txt`: install backend dependencies
- `cd annotator && pip install -r requirements.txt`: install annotator dependencies
- `cd backend && PYTHONPATH=. pytest`: run backend tests
- `cd annotator && PYTHONPATH=. pytest`: run annotator tests

Use `PYTHONPATH=.` for Python tests so imports like `from app import create_app` resolve correctly.

## Coding Style & Naming Conventions

- Python: 4-space indentation, snake_case for functions/modules, PascalCase for classes
- TypeScript/React: PascalCase for components, camelCase for hooks, stores, and utilities
- Keep Flask route handlers thin; place business logic in `app/services/`
- Prefer descriptive filenames like `test_export_service.py` and `TaskDetailPage.tsx`

No dedicated lint config is checked in here, so match the surrounding style and keep imports/order tidy.

## Testing Guidelines

Python tests use `pytest`. Place backend tests in `backend/tests/` and annotator tests in `annotator/tests/`. Name files `test_*.py` and keep test names behavior-focused, for example `test_export_uses_manually_updated_annotations`.

For frontend changes, at minimum run `npm run build`. For API or service changes, run the relevant `pytest` suite before opening a PR.

## Commit & Pull Request Guidelines

Recent local history is not descriptive, so use clear imperative commit messages, for example `fix export annotation fallback` or `add GHCR image publish workflow`.

PRs should include:

- a short summary of what changed
- affected areas (`backend`, `frontend`, `annotator`, infra)
- test/build commands you ran
- screenshots for visible frontend changes

## Security & Configuration Tips

Do not commit real API keys or secrets. Start from `.env.example`/compose defaults and override via environment variables. Treat `STORAGE_ROOT`, JWT secrets, encryption keys, and external provider credentials as environment-specific.
