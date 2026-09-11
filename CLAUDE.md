# Project rules — Stock Hyperion (repo: stock-intelligence-saas)

These rules are durable and apply to every session working in this repo.

## 1. Auto commit + push after every phase or logical sub-step

Once code for a phase (or a meaningful sub-step within a phase) is written, runs successfully, and its tests pass, **commit and push immediately — both, every time, without being asked.** Do not wait for explicit confirmation to commit or to push in this repo; that confirmation is granted in advance by this file. Still follow normal git hygiene: logically separated commits, real commit messages, never force-push, never skip hooks.

## 2. Data quality and point-in-time correctness come first

This is the single most important engineering principle in this project (see `docs/ai-stock-ranking-mvp-spec.md` §3/§27). If a known data-integrity or point-in-time-correctness issue is discovered — missing data silently excluded, a look-ahead leak, a provider returning wrong/incomplete values — **fix it before moving on to the next phase**, even if that means pausing the planned sequence. Do not carry a known correctness problem forward "to fix later" once it's been identified.

## 3. Always report honestly — radical transparency

Never hide, soften, or oversell results. Weak, negative, or null findings (a model with no real ranking skill, a feature that's 100% missing, a metric that came back worse than expected) get reported exactly as found, with the real numbers. This applies to model performance, data completeness, and test results alike — this project's own product principle (§14, §23) applies to how its own development is reported too.

## 4. Follow the phase order in the spec

`docs/ai-stock-ranking-mvp-spec.md` §26 defines the phase sequence. Follow it in order; don't skip ahead or reorder phases without the user explicitly asking for that.

## 5. The spec docs are the single source of truth — update them, don't silently diverge

`docs/ai-stock-ranking-mvp-spec.md` and `docs/api-and-schema-plan.md` are authoritative. If implementation surfaces a real reason to deviate from what they say (e.g. a provider's free tier doesn't actually work as planned, a schema field needs to change), **update the relevant section of the spec with the reasoning**, rather than quietly implementing something different from what's documented. Keep the original plan noted for reference when amending it.
