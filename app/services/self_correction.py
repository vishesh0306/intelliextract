from dataclasses import dataclass, field

from app.schemas.invoice import InvoiceFields
from app.services.ai_extraction import extract_invoice_fields
from app.services.validation import validate_invoice

# 1 initial attempt + 2 retries, per spec: "capped at 2 retries."
MAX_ATTEMPTS = 3

_INVOICE_FIELD_NAMES = ("invoice_number", "date", "vendor", "line_items", "total")

# Confidence heuristic, not real per-token probabilities: Groq's JSON-mode
# structured output doesn't reliably expose logprobs mappable back to
# individual JSON fields, and the spec explicitly allows "a heuristic based
# on whether validation passed" as the fallback. A field's score reflects
# how much correction the whole extraction needed to pass (fewer attempts,
# and never being named in a validation error, means higher confidence)
# rather than the model's internal certainty.
_CONFIDENCE_BY_ATTEMPT = {1: 0.95, 2: 0.75, 3: 0.55}
_NEEDS_REVIEW_CONFIDENCE = 0.3
_IMPLICATED_FIELD_PENALTY = 0.6


@dataclass
class AttemptRecord:
    attempt_number: int
    prompt: str
    raw_response: str
    errors: list[tuple[str, str]]


@dataclass
class InvoiceExtractionOutcome:
    fields: InvoiceFields | None
    attempts: list[AttemptRecord] = field(default_factory=list)
    confidence_scores: dict[str, float] | None = None
    needs_review: bool = False


async def run_invoice_self_correction(raw_text: str) -> InvoiceExtractionOutcome:
    """Ask the LLM for structured invoice fields, validate the result, and
    — if validation fails — re-prompt with the specific errors, up to
    MAX_ATTEMPTS total. This is the self-correction loop: each retry tells
    the model exactly what was wrong last time rather than just trying
    again blind.

    Returns the best-effort parsed fields even when validation never fully
    passes (needs_review=True) — a human reviewing a NEEDS_REVIEW job
    should see the model's closest attempt, not nothing.
    """
    attempts: list[AttemptRecord] = []
    implicated_fields: set[str] = set()
    previous_errors: list[str] | None = None
    last_parsed: InvoiceFields | None = None

    for attempt_number in range(1, MAX_ATTEMPTS + 1):
        ai_result = await extract_invoice_fields(raw_text, previous_errors=previous_errors)

        if ai_result.parsed is not None:
            last_parsed = ai_result.parsed
            errors = validate_invoice(ai_result.parsed)
        else:
            errors = ai_result.parse_errors

        attempts.append(
            AttemptRecord(
                attempt_number=attempt_number,
                prompt=ai_result.prompt,
                raw_response=ai_result.raw_response,
                errors=errors,
            )
        )

        if not errors:
            confidence = _score_confidence(
                attempt_number=attempt_number,
                needs_review=False,
                implicated_fields=implicated_fields,
            )
            return InvoiceExtractionOutcome(
                fields=last_parsed,
                attempts=attempts,
                confidence_scores=confidence,
                needs_review=False,
            )

        implicated_fields.update(field_name for field_name, _ in errors)
        previous_errors = [message for _, message in errors]

    confidence = (
        _score_confidence(
            attempt_number=MAX_ATTEMPTS, needs_review=True, implicated_fields=implicated_fields
        )
        if last_parsed is not None
        else None
    )
    return InvoiceExtractionOutcome(
        fields=last_parsed, attempts=attempts, confidence_scores=confidence, needs_review=True
    )


def _score_confidence(
    *, attempt_number: int, needs_review: bool, implicated_fields: set[str]
) -> dict[str, float]:
    base = _NEEDS_REVIEW_CONFIDENCE if needs_review else _CONFIDENCE_BY_ATTEMPT[attempt_number]
    return {
        name: round(base * _IMPLICATED_FIELD_PENALTY, 2) if name in implicated_fields else base
        for name in _INVOICE_FIELD_NAMES
    }
