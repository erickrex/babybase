# BabyBase

Tinder for baby names — a mobile-first web app where partners swipe on baby names together. When both parents like the same name, it's a match.

## Tech Stack

- **Backend**: Django 5.x + Django REST Framework (API-only)
- **Frontend**: React 19 (Vite) + TypeScript + Tailwind CSS
- **Database**: PostgreSQL
- **Vector Search**: Qdrant (semantic name recommendations)
- **Embeddings**: OpenAI `text-embedding-3-small`
- **Auth**: Token-based via DRF
- **Python Package Manager**: UV

## Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 15+
- [UV](https://docs.astral.sh/uv/getting-started/installation/) (Python package manager)
- Qdrant instance (cloud or local) — optional for basic dev
- OpenAI API key — optional for basic dev

## Setup

### 1. Clone and install

```bash
# Backend
cp .env.example .env        # Edit with your DB credentials
uv sync                     # Install Python dependencies

# Frontend
cd frontend
cp .env.example .env        # Set VITE_API_BASE_URL if needed
npm install
```

### 2. Database

```bash
# Create the database
createdb babybase

# Run migrations
uv run python manage.py migrate

# Create a superuser (optional)
uv run python manage.py createsuperuser
```

### 3. Run development servers

```bash
# Backend (port 8000)
uv run python manage.py runserver 0.0.0.0:8000

# Frontend (port 5173) — in a separate terminal
cd frontend && npm run dev
```

## Environment Variables

### Backend (`.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | insecure dev key | Django secret key |
| `DEBUG` | `True` | Debug mode |
| `DB_NAME` | `babybase` | PostgreSQL database name |
| `DB_USER` | `postgres` | Database user |
| `DB_PASSWORD` | `postgres` | Database password |
| `DB_HOST` | `localhost` | Database host |
| `DB_PORT` | `5432` | Database port |
| `QDRANT_URL` | — | Qdrant instance URL |
| `QDRANT_API_KEY` | — | Qdrant API key |
| `OPENAI_API_KEY` | — | OpenAI API key (for embeddings) |
| `LOG_LEVEL` | `INFO` | Logging level for `core` logger |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Allowed CORS origins |

### Frontend (`frontend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | Backend API URL |

## API Endpoints

All endpoints are under `/api/v1/`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register/` | Register new user |
| POST | `/auth/login/` | Login, returns token |
| GET | `/profile/me/` | Get current user profile |
| PATCH | `/profile/me/` | Update profile |
| POST | `/couples/invite/` | Invite partner |
| GET | `/couples/me/` | Get couple status |
| POST | `/onboarding/preferences/` | Save onboarding preferences |
| POST | `/recommendations/deck/` | Generate recommendation deck |
| GET | `/recommendations/deck/:id/` | Get existing deck |
| POST | `/swipes/` | Record a swipe |
| GET | `/matches/` | List mutual matches |
| GET | `/matches/:name_id/` | Match detail |
| GET | `/matches/:name_id/similar/` | Similar names |
| GET/POST | `/shortlist/` | View/manage shortlist |
| GET | `/constellation/` | 2D name map data |
| GET | `/health/` | Health check |

## Commands

```bash
# Backend
uv run python manage.py runserver 0.0.0.0:8000   # Start server
uv run pytest                                     # Run tests
uv run ruff check .                               # Lint
uv run ruff format .                              # Format

# Frontend
cd frontend && npm run dev                        # Dev server
cd frontend && npm run build                      # Production build
cd frontend && npm run lint                       # ESLint
cd frontend && npm run test                       # Vitest
```

## Project Structure

```
babybase/
├── config/              # Django project settings
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── core/                # Main Django app
│   ├── models.py        # User, Couple, Name, Swipe, MutualMatch, etc.
│   ├── views/           # DRF views (auth, couples, swipes, recommendations)
│   ├── serializers/     # DRF serializers
│   ├── services/        # Business logic (recommendations, scoring, Qdrant)
│   ├── middleware.py    # Request logging
│   ├── throttles.py     # Rate limiting
│   └── tests/           # pytest tests
├── frontend/            # React (Vite) app
│   └── src/
│       ├── pages/       # Route-level components
│       ├── components/  # Reusable UI
│       ├── contexts/    # Auth, Couple context
│       ├── services/    # API client (axios)
│       ├── hooks/       # Custom React hooks
│       └── theme/       # Design tokens
├── .env.example
├── pyproject.toml
└── uv.lock
```

## How It Works

1. **Register** — both partners create accounts
2. **Invite** — one partner invites the other by email
3. **Onboard** — each partner sets name preferences (backgrounds, style, gender, length)
4. **Swipe** — a recommendation deck is generated using semantic search (Qdrant) and multi-signal scoring; partners swipe independently
5. **Match** — when both parents like the same name, it becomes a mutual match
6. **Shortlist** — promote top matches to a shortlist for final decision
