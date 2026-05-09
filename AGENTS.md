# Repository Guidelines

## Product

BabyBase is a "Tinder for baby names" — a mobile-first web app where partners swipe on baby names together. When both parents like the same name, it's a match. The app helps couples find names they both love without endless debates.

## Tech Stack

- **Backend**: Django 5.x + Django REST Framework (API-only, no templates)
- **Frontend**: React 19 (Vite) + TypeScript + Tailwind CSS
- **Database**: PostgreSQL
- **Vector Search**: Qdrant (semantic name recommendations)
- **Embeddings**: OpenAI `text-embedding-3-small`
- **Package Manager (Python)**: UV
- **Package Manager (Frontend)**: npm
- **Auth**: Token-based auth via DRF
- **Testing**: pytest + pytest-django + Hypothesis (property-based)
- **Linting**: ruff (Python), ESLint (frontend)

## Project Structure

```
babybase/
├── core/                        # Main Django app
│   ├── models.py               # All data models
│   ├── views/                  # DRF views, split by domain
│   ├── serializers/            # DRF serializers, split by domain
│   ├── services/               # Business logic (scoring, matching, recommendations)
│   ├── urls.py                 # API route registration
│   ├── middleware.py           # Request logging middleware
│   ├── throttles.py            # Rate limiting classes
│   ├── pagination.py           # Custom pagination
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
│   │   ├── contexts/           # React Context providers (auth, couple)
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
cd frontend && npm run test                # Vitest
```

## API Base URL

- Backend API: `http://localhost:8000/api/v1/`
- Frontend dev server: `http://localhost:5173`
- Frontend connects to backend via `VITE_API_BASE_URL` env var

---

## Python Best Practices

### Style & Naming

- PEP 8 via ruff (line-length 120), 4-space indentation
- `snake_case` for functions/variables, `PascalCase` for classes
- Type hints on all function signatures — parameters and return types
- Use `from __future__ import annotations` only if needed for forward refs
- Docstrings on all public functions (one-liner or Google style)
- Imports ordered: stdlib → third-party → local (enforced by ruff `I` rule)

### Logging

- Every module gets its own logger: `logger = logging.getLogger(__name__)`
- Use structured log messages with `%s` formatting (not f-strings): `logger.info("User registered: %s", user.email)`
- Log levels:
  - `DEBUG` — per-request details (individual swipes, query results)
  - `INFO` — significant actions (login, registration, deck generation, match created)
  - `WARNING` — recoverable issues (failed login, validation rejection, filter fallback)
  - `ERROR` — unexpected failures (external API errors, unhandled exceptions)
- Never log passwords, tokens, or full request bodies
- Use `logger.exception()` inside except blocks to capture tracebacks
- Configure via `LOG_LEVEL` env var (default: `INFO`)

### Error Handling

- Catch specific exceptions — never bare `except Exception`
- Services raise domain-specific exceptions (e.g., `SwipeValidationError`, `CoupleExistsError`)
- Views catch service exceptions and map to appropriate HTTP status codes
- External API calls (OpenAI, Qdrant) wrapped in try/except with logging
- Use `logger.exception()` for unexpected errors — it auto-includes the traceback
- Return clean error responses to the client — never expose internal details

### Service Layer

- Business logic lives in `core/services/`, never in views or serializers
- Services return data (models, dicts, tuples) — never HTTP responses
- Services are stateless functions (not classes) unless state is genuinely needed
- Each service module has a single responsibility (couples, swipes, recommendations, etc.)
- Services call other services when needed — views only call one service per action
- Handle duplicates gracefully (catch `IntegrityError`, return existing record)

### Views

- Views handle HTTP only: parse request → validate → call service → serialize → respond
- Use function-based views with `@api_view` decorator (not class-based ViewSets for simple endpoints)
- Always validate with a serializer before calling the service layer
- Consistent response format: `{"status": "success"|"error", "data": {...}, "message": "..."}`
- Consistent error format: `{"status": "error", "message": "...", "errors": {...}}`
- Rate limiting on login (5/15min) and general API (1000/hour)
- Log failed operations at WARNING level, successful mutations at INFO level

### Models & Database

- UUID primary keys on all models via abstract `BaseModel` with `id`, `created_at`, `updated_at`
- Use `TextChoices` for enums, not raw strings
- Always set `related_name` on ForeignKey/OneToOneField
- Use database `UniqueConstraint` and `CheckConstraint` — don't rely on `clean()` alone
- Choose `on_delete` deliberately: `CASCADE` for children, `PROTECT` for critical refs, `SET_NULL` for optional
- Always use `select_related` (ForeignKey/OneToOne) and `prefetch_related` (ManyToMany/reverse FK)
- Use `.exists()` not `.count()` for boolean checks
- Use `.update()` for bulk operations, `F()` for atomic field updates
- Add indexes based on actual query patterns
- Production: `CONN_MAX_AGE=600`, `CONN_HEALTH_CHECKS=True`

### Serializers

- Separate serializers for list vs. detail vs. create when field sets differ
- Input validation in serializers, business validation in services
- Use `write_only=True` for passwords and sensitive input fields
- Normalize email to lowercase in `validate_email`

### Testing

- Tests live in `core/tests/` and follow `test_*.py` naming
- Use pytest + pytest-django as the test runner
- Use Hypothesis for property-based tests on scoring/matching logic
- Use factory_boy for test data generation
- Test the service layer independently from views
- Add or update tests with every behavior change
- Test edge cases: null data, duplicate operations, missing relationships

### Migration Discipline

- Never edit a migration that has been applied in production — create a new one
- Name migrations descriptively: `--name add_name_style_index`
- Use `RunPython` with `apps.get_model()` for data migrations; always provide a reverse function
- Zero-downtime pattern: add nullable column → backfill → update code → remove old column (separate deploys)

---

## TypeScript / React Best Practices

### Style & Naming

- Functional components only — no class components
- `PascalCase` for component filenames and component names (e.g., `SwipeScreen.tsx`)
- `camelCase` for variables, hooks, functions, and non-component files
- Explicit return types on exported functions and hooks
- Use `interface` for object shapes, `type` for unions/intersections
- Prefer `const` over `let`; never use `var`

### Component Patterns

- Keep components small (< 100 lines); extract to hooks when logic exceeds ~20 lines
- Extract to a reusable component when used in 2+ places
- Pages compose components; business logic lives in hooks or context, not in page components
- Props interfaces defined above the component, exported if needed externally
- Destructure props in the function signature
- Use early returns for guard clauses and loading/error states

### State Management

- Auth state in React Context (`AuthContext`); token persisted in localStorage
- Couple state in React Context (`CoupleContext`)
- Local component state with `useState` for UI-only concerns
- Avoid prop drilling beyond 2 levels — use context or composition instead
- Derive state from existing state rather than duplicating it

### API & Data Fetching

- Centralized API client (axios) in `services/api.ts`
- Auth token interceptor attaches `Token <key>` header automatically
- Skip auth header for public endpoints (login, register)
- Auto-logout on 401 responses (except for login/register endpoints)
- Handle rate limiting (429) with specific user-facing messages
- Type API responses with interfaces matching the backend contract

### Styling

- Tailwind CSS for all styling — mobile-first breakpoints
- Design tokens in `theme/colors.ts` and `theme/tokens.ts` — never hardcode colors or spacing
- Use semantic color names (e.g., `text-primary`, `bg-card`) not raw hex values
- Responsive: design for 375px width first, scale up with `sm:`, `md:`, `lg:` breakpoints

### Error Handling (Frontend)

- Wrap API calls in try/catch; display user-friendly error messages
- Distinguish between network errors, validation errors (400), auth errors (401), and rate limits (429)
- Never show raw error objects or stack traces to users
- Use error boundaries for unexpected render failures

### Hooks

- Custom hooks in `hooks/` for reusable data-fetching or business logic
- Prefix with `use` (e.g., `useDeck`, `useMatches`)
- Return loading/error/data tuple pattern: `{ data, isLoading, error }`
- Clean up subscriptions and timers in `useEffect` return

### File Organization

- One component per file (exception: small helper components used only by the parent)
- Co-locate tests with source: `Component.test.tsx` next to `Component.tsx`
- Index files (`index.ts`) only for barrel exports from directories

---

## Scoring & Matching System

- Multi-signal relevance scorer: each signal is an independent method returning `float` in [0.0, 1.0]
- **Null-safety contract**: if either party has missing data for a signal, return 0 (never crash, never penalize)
- Weighted composition: `final = Σ(signal_i × weight_i)`
- Weights: semantic 0.35, couple_overlap 0.20, filter_fit 0.15, bridge 0.10, novelty 0.10, diversity 0.10
- Top-N cap before expensive scoring (default 50) to prevent O(n²)
- Server-side swipe validation: re-check filters before recording (frontend data may be stale)
- Match detection: both parents must have `action='like'` on the same name within the same couple
- Duplicate swipes handled gracefully (return existing, no error)
- Deck caching: check for unexpired deck before regenerating

---

## Commit & Pull Request Guidelines

- Conventional Commits: `feat:`, `fix:`, `refactor:`, `chore:`, `docs:`, `test:`
- One logical change per commit
- PRs include: summary, test evidence, screenshots for UI changes

---

## Infrastructure & Deployment

- `entrypoint.sh` only does: migrate + start server. Nothing else.
- Never add one-off commands (seed, createsuperuser) to entrypoint — use SSM or run locally
- ALLOWED_HOSTS: set via env var + auto-detect EC2 IP from instance metadata in production
- S3 for media/static in production, local filesystem in dev (toggle via `USE_S3_STORAGE` env var)
- Secrets auto-generated by CDK/IaC — never manually create or commit

---

## Security & Configuration

- Copy `.env.example` before local runs
- Never commit secrets, tokens, or credentials
- Use `python-decouple` for env-based config
- CORS locked to specific origins in production
- Argon2 as primary password hasher
- `DEBUG=False` in production, `SECRET_KEY` has no default (fails fast if missing)
- File upload size limits in both Django settings AND nginx/reverse proxy
- Webhook signatures verified (HMAC) for any external integrations
- Password validation: minimum 8 chars, common password check, numeric-only check, attribute similarity check

---

## Anti-Patterns to Avoid

| Don't | Do Instead |
|---|---|
| Business logic in views or serializers | Service layer (`core/services/`) |
| God model with 40+ fields | Split with OneToOneField |
| Bare `except Exception` | Catch specific exceptions, log with `logger.exception()` |
| N+1 queries in loops | `select_related` / `prefetch_related` |
| Hardcoded colors/spacing in frontend | Design tokens from `theme/` |
| Editing applied migrations | Create new migrations |
| One-off commands in entrypoint.sh | SSM or local management commands |
| Inline styles everywhere | Tailwind utility classes |
| Frontend components doing business logic | Extract to hooks/context |
| Scoring that penalizes missing data | Missing data = 0 (neutral) |
| Storing match as two rows (A→B and B→A) | Normalize pair (lower ID = user1) |
| Trusting frontend swipe data blindly | Re-validate server-side |
| f-strings in log messages | `%s` formatting: `logger.info("msg: %s", val)` |
| Logging passwords or tokens | Log user IDs/emails only |
| Swallowing errors silently | Log + re-raise or return clean error |
| `any` type in TypeScript | Define proper interfaces |
| Prop drilling beyond 2 levels | Use React Context or composition |
| Raw HTTP status codes in frontend | Named constants or specific error handling per code |
| Mixing dev and prod dependencies | Separate `[dependency-groups]` in pyproject.toml |
| Class-based views for simple endpoints | Function-based views with `@api_view` |
| Manual JSON parsing in views | DRF serializers for all input validation |
