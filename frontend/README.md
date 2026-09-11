# Frontend — Stock Hyperion dashboard

Next.js (App Router) + TypeScript + Tailwind CSS v4 frontend for Stock
Hyperion's rankings dashboard (spec §19/§26 Phase 9). Three public pages
built from the approved design mockups in `docs/design/`:

- `/` — Main dashboard (latest ranking, last 7 days, 7-day stat tiles)
- `/day/[date]` — a specific past day's full detail + outcome
- `/stocks/[ticker]` — stock detail, price chart (`lightweight-charts`), fundamentals, news, prediction history
- `/admin` — single-password admin panel (job health, data-quality alerts, challenger approve/reject, credit balance, news-rollout progress)

## Running

Via docker-compose (from the repo root, alongside `db`/`backend`):

```bash
docker compose up -d db backend frontend
```

Or standalone against an already-running backend:

```bash
npm install
npm run dev
```

Environment variables (see root `.env.example`):

- `BACKEND_INTERNAL_URL` — base URL the Next.js server uses for its own
  server-rendered fetches (inside docker-compose: the `backend` service name)
- `NEXT_PUBLIC_BACKEND_URL` — base URL the browser calls directly (admin
  login/actions); must be reachable from the user's machine
