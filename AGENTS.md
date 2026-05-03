# Repository Guidelines

## Product

BabyBase is a "Tinder for baby names" — a mobile-first web app where partners swipe on baby names together. When both parents like the same name, it's a match. The app helps couples find names they both love without endless debates.

## Tech Stack

- **Backend**: Django 5.x + Django REST Framework (API-only, no templates)
- **Frontend**: React (Vite) — mobile-first responsive web app
- **Database**: PostgreSQL
- **Package Manager (Python)**: UV
- **Package Manager (Frontend)**: npm
- **Auth**: Token-based auth via DRF
- **Testing**: pytest + pytest-django + Hypothesis (property-based)
- **Linting**: ruff (Python), ESLint + Prettier (frontend)

## Project Structure

```
babybase/
├── core/                        # Main Django app
│   ├── models.py               # All data models
│   ├── views/                  # DRF ViewSets, split by domain
│   ├── serializers/            # DRF serializers, split by domain
│   ├── services/               # Business logic (scoring, matching, filters)
│   ├── urls.py                 # API route registration
│   ├── permissions.py          # Custom permission classes
│   ├── signals.py              # Auto-create related objects
│   ├── management/commands/    # Custom management commands
│   ├── fixtures/               # Seed data (JSON)
│   └── tests/                  # Backend tests
│
├── config/                      # Django project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
│
├── frontend/                    # React (Vite) app — mobile-first web
│   ├── src/
│   │   ├── pages/              # Page-level components (one per route)
│   │   ├── components/         # Reusable UI components
│   │   ├── contexts/           # React Context providers (auth, theme)
│   │   ├── services/           # API client (axios)
│   │   ├── hooks/              # Custom React hooks
│   │   ├── theme/              # Design tokens, colors, spacing
│   │   └── utils/              # Pure utility functions
│   ├── index.html
│   ├── vite.config.ts
│   └── package.json
│
├── .env.example
├── pyproject.toml
├── Dockerfile
├── entrypoint.sh
└── README.md
```

## Build, Test, and Development Commands

```bash
# Backend
uv sync                                    # Install Python deps
uv run python manage.py migrate            # Run migrations
uv run python manage.py runserver 0.0.0.0:8000  # Start backend (port 8000)
uv run pytest                              # Run all backend tests
uv run ruff check .                        # Lint
uv run ruff format .                       # Format

# Frontend
cd frontend && npm install                 # Install frontend deps
cd frontend && npm run dev                 # Start Vite dev server (port 5173)
cd frontend && npm run build               # Production build
cd frontend && npm run lint                # ESLint
```

## API Base URL

- Backend API: `http://localhost:8000/api/v1/`
- Frontend dev server: `http://localhost:5173`
- Frontend connects to backend via `VITE_API_BASE_URL` env var

## Coding Style & Naming Conventions

### Python (Backend)
- PEP 8 via ruff, 4-space indentation
- `snake_case` for functions/variables, `PascalCase` for classes
- Business logic lives in `core/services/`, not views or serializers
- Views handle HTTP only — parse request, call service, return response
- UUID primary keys on all models
- Type hints on all function signatures

### TypeScript/React (Frontend)
- Functional components only, `PascalCase` filenames (e.g., `SwipeScreen.tsx`)
- `camelCase` for variables/hooks/functions
- CSS Modules or Tailwind for styling — mobile-first breakpoints
- Never hardcode colors or spacing — use design tokens from `theme/`
- Keep components small; extract to hooks when logic exceeds ~20 lines

## Architecture Patterns

- **Service layer**: Business logic in `core/services/`. Services return data (models/dicts), never HTTP responses. Both views and future consumers call the same services.
- **Consistent API responses**: `{"status": "success"|"error", "data": {...}, "message": ""}`
- **Scoring system**: Multi-signal relevance scorer in `core/services/relevance.py`. Each signal is an independent, null-safe, testable method.
- **Swipe mechanics**: Record swipe → check for mutual like → create match if reciprocal.

## Testing Guidelines

- Backend tests live in `core/tests/` and follow `test_*.py` naming
- Use pytest + pytest-django as the test runner
- Use Hypothesis for property-based tests on scoring/matching logic
- Use factory_boy for test data generation
- Test the service layer independently from views
- Add or update tests with every behavior change

## Commit & Pull Request Guidelines

- Conventional Commits: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`
- One logical change per commit
- PRs include: summary, test evidence, screenshots for UI changes

## Database & Model Conventions

- UUID primary keys on all models via abstract `BaseModel` with `id`, `created_at`, `updated_at`
- Use `TextChoices` for enums, not raw strings
- Always set `related_name` on ForeignKey/OneToOneField
- Use database `UniqueConstraint` and `CheckConstraint` — don't rely on `clean()` alone
- Choose `on_delete` deliberately: `CASCADE` for children, `PROTECT` for critical refs, `SET_NULL` for optional
- Always use `select_related` (ForeignKey/OneToOne) and `prefetch_related` (ManyToMany/reverse FK) in querysets
- Use `.exists()` not `.count()` for boolean checks
- Use `.update()` for bulk operations, `F()` for atomic updates
- Add indexes based on actual query patterns
- Production: `CONN_MAX_AGE=600`, `CONN_HEALTH_CHECKS=True`

## Scoring & Matching System

- Multi-signal relevance scorer: each signal is an independent method returning `int >= 0`
- **Null-safety contract**: if either party has missing data for a signal, return 0 (never crash, never penalize)
- Additive composition: total score = sum of all signal scores
- Combined ranking formula: `final = (primary * W_PRIMARY) + (relevance * W_RELEVANCE) + (completeness * W_COMPLETENESS)`
- Start with weights 2.0 / 1.0 / 0.5, tune from user feedback
- Top-N cap before expensive scoring (default 50) to prevent O(n²)
- Bidirectional preference filtering: both parties must satisfy each other's criteria
- Server-side swipe validation: re-check filters before recording (frontend data may be stale)
- Match detection: normalize pair (lower ID = user1) to prevent duplicates

## View & Serializer Patterns

- Views handle HTTP only: parse request → call service → return response
- Use `get_object_or_404` — don't catch `DoesNotExist` manually
- Separate serializers for list vs. detail vs. create when field sets differ
- Rate limiting on login (5/15min) and general API (1000/hour)
- Consistent error format: `{"status": "error", "message": "...", "errors": {...}}`

## Migration Discipline

- Never edit a migration that has been applied in production — create a new one
- Name migrations descriptively: `--name add_name_style_index`
- Use `RunPython` with `apps.get_model()` for data migrations; always provide a reverse function
- Zero-downtime pattern: add nullable column → backfill → update code → remove old column (separate deploys)

## Frontend Patterns

- Centralized API client (axios) with auth token interceptor and auto-logout on 401
- Auth state in React Context; token persisted in localStorage
- Design tokens for all colors, spacing, radii — never hardcode
- Mobile-first: design for 375px width, scale up with breakpoints
- Pages compose components; business logic lives in hooks or context, not in page components
- Extract to a component when used in 2+ places

## Infrastructure & Deployment

- `entrypoint.sh` only does: migrate + start server. Nothing else.
- Never add one-off commands (seed, createsuperuser) to entrypoint — use SSM or run locally
- ALLOWED_HOSTS: set via env var + auto-detect EC2 IP from instance metadata in production
- S3 for media/static in production, local filesystem in dev (toggle via `USE_S3_STORAGE` env var)
- Secrets auto-generated by CDK/IaC — never manually create or commit

## Security & Configuration

- Copy `.env.example` before local runs
- Never commit secrets, tokens, or credentials
- Use `python-decouple` for env-based config
- CORS locked to specific origins in production
- Argon2 as primary password hasher
- `DEBUG=False` in production, `SECRET_KEY` has no default (fails fast if missing)
- File upload size limits in both Django settings AND nginx/reverse proxy
- Webhook signatures verified (HMAC) for any external integrations

## Anti-Patterns to Avoid

| Don't | Do Instead |
|---|---|
| Business logic in views or serializers | Service layer (`core/services/`) |
| God model with 40+ fields | Split with OneToOneField |
| Bare `except Exception` | Catch specific exceptions |
| N+1 queries in loops | `select_related` / `prefetch_related` |
| Hardcoded colors/spacing in frontend | Design tokens from `theme/` |
| Editing applied migrations | Create new migrations |
| One-off commands in entrypoint.sh | SSM or local management commands |
| Inline styles everywhere | Extracted CSS modules or utility classes |
| Frontend components doing business logic | Extract to hooks/context |
| Scoring that penalizes missing data | Missing data = 0 (neutral) |
| Storing match as two rows (A→B and B→A) | Normalize pair (lower ID = user1) |
| Trusting frontend swipe data blindly | Re-validate server-side |
