# stock-intelligence-saas
AI-powered stock intelligence platform that ranks equities using market data, news, fundamentals, and machine learning.

See `docs/ai-stock-ranking-mvp-spec.md` for the full product spec, `docs/data-ingestion-plan.md` for provider/schedule details, and `docs/api-and-schema-plan.md` for the API surface and database schema.

## Running (Phase 1)

Requires Docker Desktop.

```
cp .env.example .env   # then fill in real values (see the repo owner for API keys)
docker compose up -d db
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend python -m app.jobs.seed_universe
docker compose run --rm backend python -m app.jobs.backfill_market_data
docker compose up backend
```

Then `GET http://localhost:8000/api/v1/health`.

Run tests (against a real Postgres test database, never SQLite):

```
docker compose run --rm backend pytest
```

