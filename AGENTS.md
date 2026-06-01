# BabyBase Agent Guide

## Purpose

This file is for coding agents working in this repository. Keep it short, current, and operational. Use [README.md](/Users/erickrea/Documents/reference_code/babybase/README.md) for setup and product background; use this file for the contracts and guardrails that matter when changing code.

## Product And Stack

BabyBase is a mobile-first "Tinder for baby names" app. Parents swipe on names; a match is created when both partners like the same active name within the same couple.

- Backend: Django 5, Django REST Framework, API-only.
- Frontend: React 19, Vite, TypeScript, Tailwind CSS.
- Data: PostgreSQL plus Qdrant for vector search.
- Embeddings: AWS Bedrock Titan Embed V2, model `amazon.titan-embed-text-v2:0`, 1024 dimensions.
- Auth: DRF token auth.
- Python package manager: `uv`.
- Frontend package manager: `npm`.
- AWS: use the locally configured AWS profile or environment credentials for the intended account. Always verify the active identity with `aws sts get-caller-identity` before running commands that touch AWS.

## Commands

Run the smallest command that verifies your change, then broaden when the change crosses boundaries.

```bash
# Backend
uv sync
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run pytest
uv run ruff check .
uv run ruff format .

# Frontend
cd frontend && npm install
cd frontend && npm run test -- --run
cd frontend && npm run build
cd frontend && npm run lint

# Infrastructure
cd infra && npm test -- --runInBand
cd infra && npm run build
```

Local services:

- Backend API: `http://localhost:8000/api/v1/`
- Frontend dev server: `http://localhost:5173`
- Frontend API base: `VITE_API_BASE_URL`
- Recommendation and similar-name flows need PostgreSQL, Qdrant, and Bedrock credentials unless tests mock those dependencies.

## Repository Map

- `core/models.py`: Django models and database constraints.
- `core/views/`: DRF function views. Keep these thin.
- `core/serializers/`: request and response validation/shape.
- `core/services/`: business rules and external integrations.
- `core/tests/`: pytest backend coverage.
- `frontend/src/services/api.ts`: centralized API client.
- `frontend/src/hooks/`: reusable data and workflow logic.
- `frontend/src/contexts/`: auth and couple state.
- `frontend/src/pages/`: route-level composition.
- `infra/`: CDK infrastructure.

## API And Behavior Contracts

Preserve these unless the user explicitly asks for a product change.

- All API responses use the envelope `{"status": "success"|"error", ...}`.
- Login normalizes email to lowercase before authentication.
- Registration runs Django password validators and preserves password confirmation errors.
- Solo onboarding is supported: a user with no couple and incomplete onboarding goes to `/onboarding/preferences`; a user with no couple and completed solo onboarding can enter the app.
- `POST /api/v1/recommendations/deck/` accepts `mode` and optional `force_refresh`.
- Deck generation reuses the latest unexpired deck for the same couple and mode when `force_refresh` is false and the cached deck still has unswiped items.
- Deck responses include `cached`; cached responses return HTTP 200 and fresh responses return HTTP 201.
- Manual deck refreshes must send `force_refresh: true`; initial deck loads should not.
- Swipes may omit `deck_id` for backward compatibility.
- When a swipe includes `deck_id`, that deck must belong to the user's couple and contain the submitted `name_id`; invalid provenance returns a clean 400.
- Duplicate swipes are graceful and must not create false matches.
- Matches are scoped to a couple and require both partners to like the same name.
- Similar-name and recommendation paths use the Titan/Qdrant vector contract above.

## Backend Rules

- Put business logic in `core/services/`, not in views or serializers.
- Views should parse the HTTP request, run serializers, call one service-level workflow, and return a serialized response.
- Serializers handle input/output shape and basic field validation. Cross-object and domain validation belongs in services.
- Services return data or raise domain exceptions. They must not return DRF `Response` objects.
- Use domain-specific exceptions where callers need clean 400/404 behavior.
- Wrap external calls to Bedrock and Qdrant with specific exception handling and logging.
- Use `select_related` and `prefetch_related` when traversing relationships in loops.
- Use `.exists()` for boolean checks and database constraints for invariants.
- Do not edit applied migrations. Create a new migration for schema changes.
- Use `%s` logging interpolation, not f-strings. Never log passwords, tokens, or full request bodies.

## Frontend Rules

- Keep API calls centralized through `frontend/src/services/api.ts`.
- Put data-fetching and workflow logic in hooks or context, not page components.
- Keep auth state in `AuthContext` and couple state in `CoupleContext`.
- Preserve the token auth header format `Token <key>`.
- Treat 400, 401, 429, network failures, and unexpected errors distinctly when surfacing messages.
- Use Tailwind and the existing theme tokens; avoid hardcoded colors and inline styles.
- Design mobile-first at 375px, then expand with responsive breakpoints.
- Avoid `any`; define interfaces that match backend response contracts.

## Scoring, Swipes, And Recommendations

- Scoring signals return floats in `[0.0, 1.0]`.
- Missing preference data is neutral: return 0 for that signal, never crash or penalize.
- Keep the weighted scoring contract: semantic 0.35, couple overlap 0.20, filter fit 0.15, bridge 0.10, novelty 0.10, diversity 0.10.
- Cap candidates before expensive scoring to avoid accidental O(n squared) work.
- Re-check server-side swipe validity because frontend data can be stale.
- Cache recommendation decks by couple and mode; regenerate only when forced, expired, or exhausted for the current user/couple.

## Testing Expectations

- Add or update tests with every behavior change.
- Prefer service tests for business rules and API tests for request/response contracts.
- Use Hypothesis for scoring and vector invariants when the behavior has broad input space.
- Frontend hook/context changes need Vitest coverage near the changed hook or component.
- For cross-boundary changes, run backend tests, frontend tests, builds, and lint before handing off.

## Security And Configuration

- Always verify the active AWS identity with `aws sts get-caller-identity` before running anything that touches AWS, including Bedrock, Polly, S3, or CDK. Use the profile or credentials explicitly chosen for the target account, and do not commit local profile names, access keys, tokens, or account-specific `.env` values.
- Never commit secrets, tokens, credentials, or generated local `.env` files.
- `SECRET_KEY` must fail fast in production when missing.
- CORS must remain explicit in production.
- Password policy includes minimum length, common password, numeric-only, and attribute similarity validation.
- Production infrastructure owns generated secrets. Do not add one-off secret creation to app startup.

## Deployment And Infra

- `entrypoint.sh` should only run migrations and start the server.
- Do not add seed data, superuser creation, or one-off maintenance commands to startup.
- Keep static/media storage controlled by environment, with S3 for production and local storage for development.
- Infrastructure changes in `infra/` need both tests and a build.

## Common Mistakes To Avoid

- Duplicating business logic between views and services.
- Trusting frontend swipe or deck data without server validation.
- Returning raw DRF validation internals in a shape that breaks the response envelope.
- Regenerating recommendation decks on every load.
- Breaking solo onboarding by requiring a couple before app access.
- Adding broad refactors while fixing a narrow bug.
- Touching migrations, generated files, or unrelated dirty worktree changes unless the task requires it.
