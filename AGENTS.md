# Repository Guidelines

## Runtime Environment

This workspace is the deployed server copy of Hyper Alpha Arena, not a disposable local clone. The project is already running on this machine and serves the production-like app on port `8802`. Treat process restarts, environment changes, database operations, OSS/CDN configuration, and cleanup tasks as live-server work: inspect current state first, avoid destructive commands, preserve existing user changes, and verify the running service after operational changes.

## Project Structure & Module Organization

This repository is split into a FastAPI backend and a Vite/React frontend.

- `backend/`: Python API, database models, migrations, services, and static deployment output.
- `backend/services/`: market data, AI decisioning, Hyper AI tools, exchange clients, storage, and collectors.
- `backend/api/` and `backend/routes/`: HTTP route modules.
- `backend/database/`: SQLAlchemy connection, models, and migration scripts.
- `frontend/app/`: React source, components, contexts, API clients, and i18n files.
- `frontend/public/`: static frontend assets, including arena sprites.
- `backend/static/`: built frontend files served by the backend.
- `claude架构/`: external architecture reference material; do not treat it as production app code.

## Build, Test, and Development Commands

- `pnpm install:all`: install frontend packages and sync backend dependencies.
- `pnpm dev`: run backend and frontend together.
- `pnpm dev:backend`: run FastAPI with reload on port `5611`.
- `pnpm dev:frontend`: run Vite locally.
- `pnpm build`: build frontend, then run the backend build placeholder.
- `cd frontend && pnpm build`: production frontend build.
- `cd backend && uv run pytest`: run backend tests when present.
- `python3 -m py_compile <files>`: quick syntax check for touched Python files.

## Coding Style & Naming Conventions

Python uses 4-space indentation, type hints where useful, and snake_case for modules, functions, and variables. Keep service files domain-focused, for example `hyper_ai_*`, `ai_decision_*`, and exchange-specific modules. Backend dev dependencies include `black` and `ruff`; use them for touched Python files when practical.

Frontend code uses TypeScript/React components in PascalCase, hooks and helpers in camelCase, and 2-space indentation. Prefer existing UI patterns, shared API helpers in `frontend/app/lib/`, and lucide icons.

## Mandatory File Size Rule

All future source-code additions and modifications must strictly keep every touched source file at or below 500 lines. This is a hard rule, not a preference.

- Before adding logic to an existing file, check its current line count.
- Do not add new logic to a file that is already over 500 lines. Split it by responsibility first.
- If a change makes any touched source file exceed 500 lines, split helpers, route handlers, UI subcomponents, schemas, collectors, tool definitions, or service logic into focused modules before finishing.
- Existing oversized legacy files should not grow. When touching one, reduce or split it as part of the same change.
- Each module should have one clear job and a stable ownership boundary so future AI and human edits remain easy to review.
- Generated build artifacts and vendored dependency files are not edited manually; source files remain subject to the 500-line rule.

## Testing Guidelines

There is no broad enforced coverage gate yet. Add focused tests for risky backend logic under nearby test modules or `backend/tests/` if introduced. Name Python tests `test_*.py`. For frontend changes, run `cd frontend && pnpm build`.

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries such as `Fix DeepSeek Anthropic history restoration` or `Add CoinIcon for watchlist and position displays`. Keep commits scoped. Pull requests should include a concise summary, verification commands, linked issues when applicable, and screenshots for UI changes.

## Security & Configuration Tips

Never commit real API keys, wallet private keys, database URLs, or OSS credentials. Use `.env` and `.env.example` for configuration shape only. Mask secrets in logs and tool traces, and keep real-money trading changes behind explicit confirmation and clear environment checks.

## Aliyun OSS & CDN

Use Aliyun OSS for user uploads, message archives, and high-volume market-data archives so large data does not stay on the app server. Configure uploads with `UPLOAD_STORAGE_MODE=oss`, `UPLOAD_STORAGE_OSS_BUCKET`, `UPLOAD_STORAGE_OSS_ENDPOINT`, `UPLOAD_STORAGE_OSS_REGION`, `UPLOAD_STORAGE_OSS_ACCESS_KEY_ID`, and `UPLOAD_STORAGE_OSS_ACCESS_KEY_SECRET`.

Expose uploaded public assets through CDN by setting `UPLOAD_PUBLIC_BASE_URL` to the CDN or OSS domain that actually serves the bucket. Do not point it to the app SPA domain unless that path is routed to OSS. For data archives, use `MESSAGE_ARCHIVE_OSS_BUCKET`, `MARKET_DATA_ARCHIVE_OSS_BUCKET`, and `MARKET_DATA_ARCHIVE_OSS_CACHE_CONTROL`. Keep private archives with restrictive cache settings; only public upload assets should use long CDN cache headers.
