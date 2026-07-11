import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.schemas.invoice import InvoiceFields
from app.services.llm.factory import get_llm_client

_INVOICE_SYSTEM_PROMPT = """You are a precise document data extraction engine.

Extract invoice fields from the raw text of an invoice and respond with
ONLY a single JSON object — no markdown fences, no commentary — matching
exactly this JSON schema:

{schema}

Rules:
- If a field's value cannot be found in the text, make your best reasonable
  inference from context; never invent a line item that isn't present in
  the text.
- "date" must be a string, formatted YYYY-MM-DD if the source format allows it.
- "total", and each line item's "quantity"/"unit_price"/"amount", must be numbers, not strings.
- Only include "subtotal", "tax_amount", "discount_amount", or
  "adjustment_amount" if the document states that figure separately from
  the final total (e.g. a printed "Subtotal", "GST", "Tax", "Discount", or
  "Less: Advance Paid" line). Leave them out entirely for a simple invoice
  with no such breakdown — do not guess or back-calculate them.
"""


@dataclass
class AIExtractionResult:
    parsed: InvoiceFields | None
    prompt: str
    raw_response: str
    # (field, message) pairs from Pydantic when `parsed` is None — empty
    # whenever parsing succeeded, same shape as validate_invoice()'s
    # business-rule errors so callers handle both uniformly.
    parse_errors: list[tuple[str, str]] = field(default_factory=list)


async def extract_invoice_fields(
    raw_text: str, *, previous_errors: list[str] | None = None
) -> AIExtractionResult:
    """One LLM call, best-effort parsed against InvoiceFields.

    Pass `previous_errors` (from a prior attempt's schema or business-rule
    validation) to re-prompt with exactly what went wrong — the
    self-correction loop in app/services/self_correction.py drives this
    across retries; this function itself has no retry logic of its own.
    """
    schema_json = json.dumps(InvoiceFields.model_json_schema())
    system_prompt = _INVOICE_SYSTEM_PROMPT.format(schema=schema_json)

    user_prompt = raw_text
    if previous_errors:
        errors_text = "\n".join(f"- {message}" for message in previous_errors)
        user_prompt = (
            f"{raw_text}\n\n"
            f"Your previous extraction of this same document had the following "
            f"problems. Fix them and re-extract:\n{errors_text}"
        )

    raw_response = await get_llm_client().complete_json(
        system_prompt=system_prompt, user_prompt=user_prompt
    )

    parse_errors: list[tuple[str, str]] = []
    try:
        parsed = InvoiceFields.model_validate_json(raw_response)
    except ValidationError as exc:
        parsed = None
        parse_errors = [
            (".".join(str(part) for part in err["loc"]) or "root", err["msg"])
            for err in exc.errors()
        ]

    prompt_record = json.dumps(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )
    return AIExtractionResult(
        parsed=parsed, prompt=prompt_record, raw_response=raw_response, parse_errors=parse_errors
    )
