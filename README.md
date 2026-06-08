# BabyBase

Tinder for baby names - a mobile-first web app where partners swipe on baby names together. When both parents like the same name, it's a match.

## Tech Stack

- **Backend**: Django 5.x + Django REST Framework (API-only)
- **Frontend**: React 19 (Vite) + TypeScript + Tailwind CSS
- **Database**: PostgreSQL
- **Vector Search**: Qdrant (semantic, phonetic, and cross-cultural name retrieval)
- **Embeddings**: AWS Bedrock Titan Embed V2 `amazon.titan-embed-text-v2:0`
- **Auth**: Token-based via DRF
- **Python Package Manager**: UV

## Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 15+
- [UV](https://docs.astral.sh/uv/getting-started/installation/) (Python package manager)
- Qdrant instance (cloud or local) - required for recommendation decks, similar-name search, and the constellation map
- AWS credentials configured for Bedrock Runtime when producing embeddings. BabyBase uses Titan Embed V2, model `amazon.titan-embed-text-v2:0`.

## Setup

### 1. Install dependencies

```bash
# Backend
cp .env.example .env
uv sync

# Frontend
cd frontend
cp .env.example .env
npm install
```

Edit `.env` before running the app. At minimum, set PostgreSQL connection values, `QDRANT_URL`, and the AWS Bedrock region used for embeddings.

For local Qdrant without an API key:

```env
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
QDRANT_COLLECTION=names_global_v1
AWS_BEDROCK_REGION=us-east-1
```

### 2. Start local infrastructure

PostgreSQL must be running and accessible using the credentials in `.env`.

For local Qdrant:

```bash
docker run --rm -p 6333:6333 -p 6334:6334 \
  -v "$(pwd)/.qdrant:/qdrant/storage" \
  qdrant/qdrant:latest
```

For Qdrant Cloud, set `QDRANT_URL` and `QDRANT_API_KEY` in `.env` instead.

### 3. Configure AWS access

Use whichever AWS credential flow is standard for your machine, such as a named AWS CLI profile, environment variables, or an application role. Verify the active account before running commands that produce embeddings with Bedrock:

```bash
export AWS_PROFILE=your-profile
export AWS_REGION=us-east-1

aws sts get-caller-identity
```

BabyBase uses Bedrock Runtime with Titan Embed V2 for embeddings:

```text
amazon.titan-embed-text-v2:0
```

The embedding model returns 1024-dimensional vectors. The app validates this dimension before indexing or querying Qdrant.

### 4. Initialize the database

```bash
# Create the database
createdb babybase

# Run migrations
uv run python manage.py migrate
```

### 5. Seed and index names

Seed the relational name metadata first. This uses bundled SSA-derived CSV files in
`core/fixtures/` so new databases do not depend on network access for the name list:

```bash
uv run python manage.py seed_real_names
```

Then build the Qdrant collection and index all active names using Titan Embed V2:

```bash
uv run python manage.py index_names_to_qdrant --force-recreate
```

Use `--force-recreate` the first time, after changing embedding models, after changing vector dimensions, or when replacing a stale Qdrant collection. It deletes local vector refs for the configured collection, recreates the Qdrant collection, and clears stored user taste vectors so they can be recomputed against the current 1024-dimensional Titan vectors.

For normal incremental indexing after adding new names:

```bash
uv run python manage.py index_names_to_qdrant
```

The command uses `QDRANT_COLLECTION` from `.env`. The default is `names_global_v1`.
If Qdrant Cloud writes are slow or timing out, lower the batch size:

```bash
uv run python manage.py index_names_to_qdrant --batch-size 5
```

Optional enrichment and map backfills:

```bash
# Generate cached phonetic profiles for active names
uv run python manage.py enrich_phonetics

# Generate stored pronunciation audio for active names
uv run python manage.py generate_pronunciations

# Compute 2D coordinates for the constellation map after Qdrant indexing
uv run python manage.py compute_projections
```

Run `enrich_phonetics` before a full reindex when you want the `phonetic_style` vector to use cached phonetic profile data. Run `compute_projections` after indexing so `/api/v1/constellation/` can return positioned names.

### 6. Optional demo data

After `seed_real_names`, you can create a demo active couple with onboarding, swipes, and matches:

```bash
uv run python manage.py seed_demo --reset
```

Demo credentials:

```text
carlos@demo.babybase.app / demo1234!
natasha@demo.babybase.app / demo1234!
```

Create an admin user if needed:

```bash
uv run python manage.py createsuperuser
```

### 7. Run development servers

```bash
# Backend (port 8000)
uv run python manage.py runserver 0.0.0.0:8000

# Frontend (port 5173) - in a separate terminal
cd frontend && npm run dev
```

Open the frontend at `http://localhost:5173`.

## Local Verification

Run the backend, frontend, and infrastructure checks before shipping changes:

```bash
# Backend
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run pytest
uv run ruff check .

# Frontend
cd frontend
npm run lint
npm run build
npm run test -- --run

# Infrastructure
cd ../infra
npm test -- --runInBand
```

Useful smoke checks:

```bash
# Backend health endpoint
curl http://localhost:8000/api/v1/health/

# Verify seeded names exist
uv run python manage.py shell -c "from core.models import Name; print(Name.objects.count())"

# Verify local vector refs exist after indexing
uv run python manage.py shell -c "from core.models import NameVectorIndexRef; print(NameVectorIndexRef.objects.count())"
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
| `QDRANT_URL` | - | Qdrant instance URL |
| `QDRANT_API_KEY` | - | Qdrant API key |
| `QDRANT_COLLECTION` | `names_global_v1` | Qdrant collection queried and indexed by the app |
| `QDRANT_TIMEOUT_SECONDS` | `180` | Qdrant client timeout for search and indexing requests |
| `AWS_BEDROCK_REGION` | `us-east-1` | AWS region for Bedrock Runtime API |
| `LOG_LEVEL` | `INFO` | Logging level for `core` logger |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Allowed CORS origins |

Additional feature-specific settings are listed in `.env.example`.

### Frontend (`frontend/.env`)

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_BASE_URL` | `http://localhost:8000/api/v1` | Backend API URL |

## Titan and Qdrant Operations

### Embedding model contract

BabyBase is standardized on AWS Bedrock Titan Embed V2:

```text
amazon.titan-embed-text-v2:0
```

The application assumes 1024-dimensional vectors end to end:

- name indexing creates three named Qdrant vectors: `semantic`, `phonetic_style`, and `cross_cultural`
- recommendation retrieval queries the `semantic` named vector
- user taste vectors are trusted only when they are 1024-dimensional
- stale vectors from older embedding models are rejected before querying Qdrant

### Reindexing rules

Run a full reindex with `--force-recreate` when:

- migrating from another embedding provider or vector dimension
- changing `QDRANT_COLLECTION`
- changing named vector configuration
- Qdrant was deleted or restored from an incompatible backup
- recommendation decks suddenly become empty after an embedding/model change

Command:

```bash
uv run python manage.py index_names_to_qdrant --force-recreate
```

Run incremental indexing when:

- new active `Name` rows were added
- metadata changed but the collection schema and embedding model did not change

Command:

```bash
uv run python manage.py index_names_to_qdrant
```

Use `--batch-size 5` or another small value when indexing into a slow remote Qdrant instance.

### Empty deck troubleshooting

If `/api/v1/recommendations/deck/` returns an error or no usable results:

1. Confirm the user completed onboarding. For partnered couples, confirm the couple is active and both partners completed onboarding.
2. Confirm `QDRANT_URL`, `QDRANT_API_KEY`, and `QDRANT_COLLECTION` point to the same collection you indexed.
3. Confirm name metadata exists:
   ```bash
   uv run python manage.py shell -c "from core.models import Name; print(Name.objects.filter(active=True).count())"
   ```
4. Confirm vector refs exist:
   ```bash
   uv run python manage.py shell -c "from core.models import NameVectorIndexRef; print(NameVectorIndexRef.objects.count())"
   ```
5. Rebuild the index:
   ```bash
   uv run python manage.py index_names_to_qdrant --force-recreate
   ```
6. Check AWS credentials and Bedrock model access:
   ```bash
   aws sts get-caller-identity
   ```

### Common errors

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `QDRANT_URL must be set` | Missing backend `.env` value | Set `QDRANT_URL`, then restart Django |
| Empty recommendations after indexing | App queries a different collection than the index command used | Set `QDRANT_COLLECTION` consistently and re-run indexing |
| Dimension mismatch mentioning `1024` | Stale vector or old Qdrant collection | Run `index_names_to_qdrant --force-recreate` |
| Bedrock access denied | AWS identity lacks `bedrock:InvokeModel` | Grant access to the Titan Embed V2 foundation model |
| Local deck generation hangs or fails | Qdrant or PostgreSQL is not running | Start local services and retry |

## API Endpoints

All endpoints are under `/api/v1/`.

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register/` | Register new user |
| POST | `/auth/login/` | Login, returns token |
| POST | `/auth/logout/` | Logout and delete the current token |
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
| GET | `/matches/:name_id/sounds-like/` | Similar-sounding names with pronunciation audio URLs when available |
| GET/POST | `/shortlist/` | View/manage finalists |
| GET | `/constellation/` | 2D name map data |
| GET | `/health/` | Health check |

Deck generation accepts:

- `mode`: one of `best_match`, `bridge_names`, `more_like_this`, `wildcard`, `cross_cultural`, or `sounds_like`
- `force_refresh`: optional boolean. Use `true` for a manual refresh; normal initial loads should omit it or send `false`.

Cached deck responses return HTTP 200 with `data.cached: true`. Freshly generated decks return HTTP 201 with `data.cached: false`.

## Commands

```bash
# Backend
uv run python manage.py runserver 0.0.0.0:8000   # Start server
uv run pytest                                     # Run tests
uv run ruff check .                               # Lint
uv run ruff format .                              # Format
uv run python manage.py seed_real_names           # Seed bundled SSA-derived names
uv run python manage.py index_names_to_qdrant     # Index active names in Qdrant
uv run python manage.py compute_projections       # Compute constellation map coordinates

# Frontend
cd frontend && npm run dev                        # Dev server
cd frontend && npm run build                      # Production build
cd frontend && npm run lint                       # ESLint
cd frontend && npm run test                       # Vitest

# Infrastructure
cd infra && npm test -- --runInBand               # CDK tests
cd infra && npm run build                         # CDK TypeScript build
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

1. **Register** - users create accounts and sign in with token auth.
2. **Onboard** - each user sets name preferences such as backgrounds, style, gender, and length.
3. **Swipe solo or together** - a user can start with solo onboarding, or invite a partner and swipe as an active couple.
4. **Generate decks** - decks are built from Qdrant retrieval and multi-signal scoring, with cached decks reused until refreshed, expired, or exhausted.
5. **Match** - when both partners like the same active name in the same couple, it becomes a mutual match.
6. **Explore** - matches can show similar names, similar-sounding names, pronunciation audio, shortlist status, and constellation map placement.
7. **Finalists** - promote top matches to a focused decision list.
