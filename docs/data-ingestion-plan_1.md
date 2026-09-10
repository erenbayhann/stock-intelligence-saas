# Data Ingestion Plan — Provider Assignments, Schedule, Formats

Companion to `ai-stock-ranking-mvp-spec.md`, §4/§6/§7/§8/§11. This maps the confirmed free-tier API keys onto the provider interfaces (`MarketDataProvider`, `NewsProvider`, `FundamentalsProvider`, `MacroDataProvider`, `FilingsProvider`) with exact roles, rate-limit math, schedule, and storage format. Every provider sits behind its interface — swapping any one for a paid plan later is a config change, not a rewrite.

Universe: S&P 100 (100 tickers). All schedule times are ET, matching the "Gece Vardiyası" prediction-cycle timeline already agreed (close 16:00 → after-hours → closed window → pre-market → open 09:30).

## 1. Provider → Role Map

| Provider | Interface role | Free-tier limit | Primary use |
|---|---|---|---|
| **Alpaca** | `MarketDataProvider` (primary) | 200 calls/min, IEX feed (not full SIP tape), historical bars back to 2016 | OHLCV bars — daily + extended-hours (pre-market/after-hours) minute bars |
| **GDELT** | `NewsProvider` (primary — per-ticker **and** macro/thematic) | Free, no key; DOC 2.0 API searches the last 3 months, undocumented rate limit — stay conservative and monitor for 429s | Per-ticker company news (via batched keyword queries, §2/§3 below) **and** broad macro/global-event news (Fed policy, tariffs, sector-wide narratives) |
| **Marketaux** | `NewsProvider` (secondary, sentiment) | 100 requests/day, 3 articles/request | Market-wide sentiment context, not per-ticker (too tight a budget) |
| **Alpha Vantage** | `FundamentalsProvider` / `MarketDataProvider` (documented fallback only) | ~25 requests/day | Not actively scheduled — reserve for spot-checks or a single specific data point Alpaca/EDGAR can't supply |
| **FMP** | `FundamentalsProvider` (secondary/cross-check, amended — see below) + `MarketDataProvider` (secondary/cross-check) | 250 calls/day | Company fundamentals/ratios (opportunistic, only for tickers not gated), EOD price cross-check |
| **FRED** | `MacroDataProvider` | Effectively unlimited for this use case | Treasury yields, Fed funds rate, CPI, and other macro series — with native point-in-time vintages |
| **SEC EDGAR** | `FilingsProvider`, `FundamentalsProvider` (primary, amended during Phase 3 — see `ai-stock-ranking-mvp-spec.md` §4) | Free, no key (requires a descriptive `User-Agent` header) | Filing metadata (8-K/10-Q/10-K/Form 4) + XBRL `companyfacts`, now the primary source for structured fundamentals (real Phase 3 testing found FMP's free tier 402s ~60% of the S&P 100) |
| **Finnhub** | *(not used in the default MVP)* | ~60 calls/min, but free tier is licensed for personal/non-commercial use — unconfirmed even at the paid Starter tier whether it permits a deployed, publicly-reachable app | Deliberately excluded to avoid both the cost and the legal ambiguity. Kept documented because it sits behind the same `NewsProvider` interface — a drop-in upgrade later (once its commercial terms are confirmed/paid) if GDELT's undocumented limits ever become a real bottleneck |

## 2. Rate-limit math (why this fits in the free tiers)

- **Alpaca (200/min):** one bars request can cover multiple symbols per call (Alpaca's bars endpoint accepts a symbol list), so a full 100-ticker daily-bar pull is 1–2 calls; a full 100-ticker extended-hours minute-bar pull is a handful more. Nightly and pre-market pulls together use well under 20 calls — massive headroom.
- **GDELT, per-ticker (undocumented limit — stay conservative):** since there's no Finnhub-style one-call-per-ticker endpoint, per-ticker coverage is done by **batching** — group tickers into small OR'd keyword queries (company name/ticker per group, ~8–10 tickers per query, well inside GDELT's query-length limit), so a full 100-ticker sweep costs ~10–12 queries instead of 100. Because the pipeline only needs news that's arrived by the ~09:00–09:15 ET lock (not continuous intraday coverage — there's no intraday re-prediction), sweeps run at 7 discrete points across the closed window + pre-market instead of every 10–15 minutes (see §3). That's 7 × ~12 ≈ **~85 queries/day** for per-ticker coverage, plus 1–2 thematic/macro queries — a real increase over the "handful/day" GDELT was carrying before, so it needs the same 429-driven backoff called out in §5, and its actual undocumented ceiling should be empirically confirmed early rather than assumed.
- **Marketaux (100/day):** far too tight for per-ticker polling (100 tickers would burn the whole day's budget in one sweep). Budget it as: 2 broad market-wide queries/day (~06:00 ET and ~08:30 ET) plus a small reserved pool (~10/day) for tickers that a same-day GDELT sweep already flagged as unusually high news volume.
- **Alpha Vantage (25/day):** not part of the scheduled pipeline at all for MVP. Keep it configured and tested, but idle — a safety valve, not a workhorse.
- **FMP (250/day):** fundamentals don't need a nightly full-universe refresh (they change quarterly). Full-universe rotation across the week (100 ÷ 7 ≈ 15/day) plus same-day refresh for any ticker with a same-day earnings/filing event (rare, a handful/day) stays well under 250/day.
- **FRED:** a fixed small set of series (~10–15) pulled once/day is trivial against FRED's allowance.
- **SEC EDGAR:** polling the submissions/full-text-search endpoints every 15–30 min for 100 CIKs is light; SEC only asks for a real `User-Agent` and reasonable pacing (no hard published cap for this volume).

## 3. Daily schedule (ET), mapped to the closed-window prediction cycle

| Time (ET) | Job | Provider(s) | What |
|---|---|---|---|
| Continuous, every 15–30 min, all day | Filings poll | SEC EDGAR | New 8-K/10-Q/10-K/Form 4 for the 100 CIKs |
| ~16:15 ET (just after close) | EOD bar + result evaluation | Alpaca (primary), FMP (cross-check) | Official daily OHLCV bar written; feeds `market_prices` and triggers the prior night's result evaluation (§13) |
| 16:00–20:00 ET | After-hours bars | Alpaca | Extended-hours minute bars → `after_hours_return` |
| ~17:00 ET | Per-ticker news sweep 1/7 | GDELT | Batched keyword queries (~12 queries) covering all 100 tickers → sentiment/event features |
| ~18:00 ET | Broad market news | Marketaux | 1 of the day's 2 broad queries |
| ~19:30 ET | Per-ticker news sweep 2/7 | GDELT | Same batching as above |
| ~20:30 ET | Macro refresh | FRED | Daily pull of the fixed macro series (most values won't have changed — that's expected and correct) |
| ~21:00 ET | Weekly fundamentals rotation slice | FMP | ~15 tickers' worth of the weekly rotation, or same-day refresh if one of today's filings was an earnings release |
| ~22:00 ET | Per-ticker news sweep 3/7 | GDELT | Same batching as above |
| ~00:30 ET | Per-ticker news sweep 4/7 | GDELT | Same batching as above |
| ~03:00 ET | Per-ticker news sweep 5/7 | GDELT | Same batching as above |
| 04:00–09:00 ET | Pre-market bars | Alpaca | Extended-hours minute bars → `pre_market_return`, `gap_percentage` |
| ~06:00 ET | Per-ticker news sweep 6/7 | GDELT | Same batching as above |
| ~08:00 ET | Broad market news | Marketaux | 2nd of the day's 2 broad queries, closer to open |
| ~08:45 ET | Per-ticker news sweep 7/7 (final) | GDELT | Last chance to catch pre-market news before the feature freeze |
| ~09:00 ET | Macro/thematic sweep | GDELT | 1–2 keyword queries for overnight macro narrative |
| ~09:00–09:15 ET | **Feature freeze → inference → final prediction lock** | (consumes everything above) | Per §11 of the master spec — this is where all providers' overnight output gets frozen into one immutable snapshot |

## 4. Format & point-in-time handling per provider

- **Alpaca bars → `market_prices`**: one row per (ticker, timestamp, session_type ∈ {regular, pre, after}), OHLCV columns, `received_time` = pull time. Since Alpaca serves IEX (not consolidated) data, tag rows with `source = 'alpaca_iex'` so a later swap to a SIP-feed provider is visible in the data, not just the code.
- **GDELT/Marketaux news → `news_articles` + `news_company_links`**: `published_time` from the provider's own timestamp (never the pull time), `received_time` = pull time, `source` = provider name. Run de-duplication (§5 of the master spec) across both news sources together — the same wire story often appears via more than one provider and must not be double-counted. Since GDELT sweeps now run 7×/day, expect a meaningful amount of re-fetching the same article across consecutive sweeps — dedup on a stable key (URL, or a title+source+date hash) rather than assuming one sweep = one set of new articles.
- **FMP/Alpha Vantage fundamentals → `fundamentals`**: `as_of`/`published_time` = the filing's actual reporting/publication date from the provider (not the pull date) — this is the field that enforces §3's point-in-time rule for fundamentals specifically.
- **SEC EDGAR filings → a `filings` table + XBRL facts → `fundamentals`**: `filed_at` from EDGAR's own metadata; XBRL `companyfacts` values carry their own point-in-time frame (`fy`, `fp`, `end`, `filed`) — use `filed`, never the period the statement describes, as the availability timestamp.
- **FRED macro series → `macro_data`**: FRED natively supports point-in-time vintages via `realtime_start`/`realtime_end` — pull with that parameter so a later-revised macro figure (e.g. a GDP revision) never leaks backward into a prediction made before the revision existed. This is a built-in feature of FRED worth using explicitly, not just a nice-to-have.

## 5. Notes / open flags for later review

- **Finnhub is deliberately excluded from the default MVP** (decided 2026-09-08): its free tier is personal/non-commercial only, and it's unconfirmed whether the paid Starter tier (~$50/mo) actually grants rights to run a deployed, publicly-reachable app — Finnhub support hasn't been asked directly, and the answer wasn't findable from public sources. Also checked and ruled out as free replacements: Tiingo (same personal-use-only restriction), Currents API (explicitly requires separate enterprise terms for customer-facing/derivative use), APITube (commercial use allowed, but its free tier's 12-hour article delay is incompatible with the ~09:00–09:15 ET lock). GDELT is the one option found with an unambiguous, verified commercial-use grant (its own Terms of Use: "available for unlimited and unrestricted use for any academic, commercial, or governmental use of any kind without fee," attribution required) — so the plan runs on GDELT (primary, per-ticker via batching) + Marketaux (secondary) instead.
  - **If Finnhub (or any non-default provider) is used at all during development, keep it strictly out of the tables that will ever feed model training** (`news_articles` and anything downstream of it) — fine for one-off plumbing/integration testing (does the `NewsProvider` interface work, does parsing/storage work), never wired into the same pipeline that accumulates real training data. Training features must come from whatever provider will actually run in production (GDELT + Marketaux) from day one of data collection, or the model trains on one provider's news characteristics and serves on another's — the same train-serve-skew problem already ruled out the GDELT-bulk-historical-backfill idea earlier in planning.
  - Finnhub stays documented here as a same-interface drop-in (§1) if it's ever needed later: either GDELT's undocumented limit turns out to be a real bottleneck, or someone gets written confirmation from Finnhub that a paid tier covers production deployment.
- **This trade-off has a real cost, worth stating plainly:** per-ticker news freshness drops from "continuously polled every 10–15 min" to "7 discrete sweeps across the closed window + pre-market" (§3). That's an acceptable fit for this product specifically because only one prediction is locked per day near open — there's no intraday re-prediction that would need continuous news — but it does mean a fast-breaking story between two sweeps (up to ~2–3 hours apart overnight) won't be reflected until the next sweep picks it up.
- Alpaca's free plan is IEX-only, not the full consolidated tape — expect its volume/price figures to under-represent true market-wide volume somewhat. Acceptable for MVP; note it in the methodology page (§15) so the "Limitations" page is honest about it.
- GDELT and Marketaux both lack hard published rate-limit documentation for the free tier — the schedule above is deliberately conservative, and GDELT in particular is now carrying meaningfully more daily query volume (~85–90/day) than before this change; monitor for 429s in the observability layer (§25) and back off automatically if seen, and treat the first week or two of real usage as a live test of whether GDELT's actual (undocumented) ceiling holds up.
