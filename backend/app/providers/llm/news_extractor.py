import json
import logging
from dataclasses import dataclass

import anthropic

logger = logging.getLogger(__name__)

# Spec §5's fixed event-category taxonomy.
EVENT_CATEGORIES = [
    "Earnings",
    "Guidance",
    "M&A",
    "New contract",
    "Product launch",
    "Lawsuit",
    "Regulatory action",
    "Management change",
    "Analyst upgrade/downgrade",
    "Dividend",
    "Share buyback",
    "Capital raise",
    "Layoffs",
    "Cybersecurity incident",
    "Macroeconomic exposure",
    "Other",
]

_MAX_RELEVANT_TICKERS = 25  # a headline naming/affecting more than this is essentially "everything" — cap defensively

_CLASSIFICATION_SCHEMA = {
    # Note: Anthropic's structured-output json_schema does not support
    # "minimum"/"maximum" on "number" properties, nor "maxItems" on "array"
    # properties (both confirmed via real 400s) — bounds are stated in the
    # description/docstring instead and enforced defensively in code below.
    "type": "object",
    "properties": {
        "relevant_tickers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Must be one of the tickers given in the company list."},
                    "relevance": {
                        "type": "number",
                        "description": "How relevant this headline is to this specific company, from 0 (barely) to 1 (directly about this company).",
                    },
                    "sentiment": {
                        "type": "number",
                        "description": "Sentiment of this headline for THIS company's stock specifically, from -1 (very negative) to 1 (very positive) — the same story can be positive for one company and negative for another (e.g. an acquirer vs. a target, a commodity price move for a producer vs. a consumer of that commodity).",
                    },
                    "event_category": {"type": "string", "enum": EVENT_CATEGORIES},
                    "importance": {
                        "type": "number",
                        "description": "Estimated market-moving importance of this headline for this company, from 0 (routine/noise) to 1 (major, market-moving).",
                    },
                },
                "required": ["ticker", "relevance", "sentiment", "event_category", "importance"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["relevant_tickers"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You extract which companies, from a given list, a news headline is relevant to, and a "
    "structured trading-relevant signal for each. Judge only from the headline and source given "
    "— do not assume facts not present. Relevance is not limited to a company being named "
    "explicitly: include a company when the headline describes something that would plausibly "
    "move its stock even without naming it — a commodity price move for a producer or heavy "
    "consumer of that commodity, a regulatory or macro change that specifically affects that "
    "company's sector, a competitor's news with a direct read-through, or an indirect reference "
    "(e.g. \"the iPhone maker\" for Apple). Only include companies from the list you were given. "
    "Return an empty list if none are genuinely relevant — do not force matches. "
    "This is a research signal, not investment advice."
)


@dataclass(frozen=True)
class TickerClassification:
    ticker: str
    relevance: float
    sentiment: float
    event_category: str
    importance: float


@dataclass(frozen=True)
class ClassificationResult:
    tickers: tuple[TickerClassification, ...]
    tokens_in: int
    tokens_out: int


class LLMProviderError(Exception):
    """Raised for any LLM-call failure. `kind` matches the data_quality_alerts
    category detail spec §5 asks for: 'insufficient_credit' | 'rate_limited' |
    'provider_error'.
    """

    def __init__(self, kind: str, message: str) -> None:
        self.kind = kind
        super().__init__(message)


class ClaudeNewsExtractor:
    """Real Claude Haiku 4.5 (Anthropic API) implementation of news signal
    extraction (spec §5) — a well-bounded classification task, not the final
    stock-price predictor. Never crashes the caller: every failure mode is
    normalized to LLMProviderError with a `kind` the caller logs as a
    data_quality_alerts row and moves on from (spec §5's failure-handling rule).

    classify() sees the FULL company universe (only ~100 tickers for the S&P
    100, cheap to list in one prompt) rather than one pre-matched company —
    this is what lets it do real content/sector-based inference (a
    commodity-price or regulatory headline correctly reaching every company
    it plausibly affects) instead of being limited to whatever a literal
    company-name substring match already found upstream.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5",
        timeout: float = 30.0,
    ) -> None:
        if not api_key:
            raise ValueError("Anthropic API key must not be empty")
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        self._model = model

    def classify(
        self, *, title: str, source: str, universe: list[tuple[str, str, str | None]]
    ) -> ClassificationResult:
        """universe: list of (ticker, company_name, sector) tuples — sector
        may be None if unknown, still useful context for sector-wide inference.
        """
        company_list = "\n".join(
            f"{ticker}: {name}" + (f" ({sector})" if sector else "") for ticker, name, sector in universe
        )
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=2000,
                system=_SYSTEM_PROMPT,
                output_config={"format": {"type": "json_schema", "schema": _CLASSIFICATION_SCHEMA}},
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Source: {source}\n"
                            f"Headline: {title}\n\n"
                            f"Company list (ticker: name (sector)):\n{company_list}"
                        ),
                    }
                ],
            )
        except anthropic.RateLimitError as exc:
            raise LLMProviderError("rate_limited", str(exc)) from exc
        except anthropic.APIStatusError as exc:
            if _looks_like_insufficient_credit(exc):
                raise LLMProviderError("insufficient_credit", str(exc)) from exc
            raise LLMProviderError("provider_error", str(exc)) from exc
        except anthropic.APIConnectionError as exc:
            raise LLMProviderError("provider_error", str(exc)) from exc

        text_block = next((b for b in response.content if b.type == "text"), None)
        if text_block is None:
            raise LLMProviderError("provider_error", "model returned no text block")

        try:
            data = json.loads(text_block.text)
        except json.JSONDecodeError as exc:
            raise LLMProviderError("provider_error", f"invalid JSON from model: {exc}") from exc

        known_tickers = {ticker for ticker, _, _ in universe}
        tickers = tuple(
            TickerClassification(
                ticker=item["ticker"],
                # The schema can't enforce numeric bounds (see _CLASSIFICATION_SCHEMA
                # note) — clamp defensively so an out-of-range model output
                # never reaches the DB.
                relevance=max(0.0, min(1.0, float(item["relevance"]))),
                sentiment=max(-1.0, min(1.0, float(item["sentiment"]))),
                event_category=item["event_category"],
                importance=max(0.0, min(1.0, float(item["importance"]))),
            )
            for item in data.get("relevant_tickers", [])[:_MAX_RELEVANT_TICKERS]
            if item.get("ticker") in known_tickers  # never trust a ticker the model invented
        )
        return ClassificationResult(
            tickers=tickers,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
        )


def _looks_like_insufficient_credit(exc: anthropic.APIStatusError) -> bool:
    # "billing_error" is Anthropic's own API error-type string for a 402 —
    # more reliable than string-matching the message.
    return getattr(exc, "type", None) == "billing_error"


# Published Claude Haiku 4.5 pricing (verified 2026-09-10) — used to compute
# job_runs.metadata.llm_cost_usd for the admin panel's credit-balance card (§15).
# Update alongside NEWS_LLM_MODEL if the model changes.
HAIKU_4_5_INPUT_USD_PER_MTOK = 1.00
HAIKU_4_5_OUTPUT_USD_PER_MTOK = 5.00


def estimate_cost_usd(tokens_in: int, tokens_out: int) -> float:
    return (
        tokens_in / 1_000_000 * HAIKU_4_5_INPUT_USD_PER_MTOK
        + tokens_out / 1_000_000 * HAIKU_4_5_OUTPUT_USD_PER_MTOK
    )
