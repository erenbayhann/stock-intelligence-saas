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

_EXTRACTION_SCHEMA = {
    # Note: Anthropic's structured-output json_schema does not support
    # "minimum"/"maximum" on "number" properties (confirmed via a real 400 —
    # "properties maximum, minimum are not supported") — the range is stated
    # in the description instead and the caller clamps defensively.
    "type": "object",
    "properties": {
        "sentiment": {
            "type": "number",
            "description": "Sentiment of this headline for the named company's stock, from -1 (very negative) to 1 (very positive).",
        },
        "event_category": {"type": "string", "enum": EVENT_CATEGORIES},
        "importance": {
            "type": "number",
            "description": "Estimated market-moving importance of this headline, from 0 (routine/noise) to 1 (major, market-moving).",
        },
    },
    "required": ["sentiment", "event_category", "importance"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You extract a structured trading-relevant signal from one news headline for one "
    "company. Judge only from the headline and source given — do not assume facts not "
    "present. This is a research signal, not investment advice."
)


@dataclass(frozen=True)
class NewsExtraction:
    sentiment: float
    event_category: str
    importance: float
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

    def extract(self, *, title: str, source: str, company_name: str, ticker: str) -> NewsExtraction:
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=300,
                system=_SYSTEM_PROMPT,
                output_config={"format": {"type": "json_schema", "schema": _EXTRACTION_SCHEMA}},
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Company: {company_name} ({ticker})\n"
                            f"Source: {source}\n"
                            f"Headline: {title}"
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

        # The schema can't enforce numeric bounds (see _EXTRACTION_SCHEMA note) —
        # clamp defensively so an out-of-range model output never reaches the DB.
        return NewsExtraction(
            sentiment=max(-1.0, min(1.0, float(data["sentiment"]))),
            event_category=data["event_category"],
            importance=max(0.0, min(1.0, float(data["importance"]))),
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
