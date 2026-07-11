import json
from dataclasses import dataclass

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
"""


@dataclass
class AIExtractionResult:
    parsed: InvoiceFields | None
    prompt: str
    raw_response: str


async def extract_invoice_fields(raw_text: str) -> AIExtractionResult:
    """Single LLM call, best-effort parse. No retry loop here — that's
    Phase 7's self-correction logic, which needs a validation failure
    reason to feed back into a second prompt. This just proves the
    prompt -> structured-JSON path works end-to-end.
    """
    schema_json = json.dumps(InvoiceFields.model_json_schema())
    system_prompt = _INVOICE_SYSTEM_PROMPT.format(schema=schema_json)

    raw_response = await get_llm_client().complete_json(
        system_prompt=system_prompt, user_prompt=raw_text
    )

    try:
        parsed = InvoiceFields.model_validate_json(raw_response)
    except ValidationError:
        parsed = None

    prompt_record = json.dumps(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text},
        ]
    )
    return AIExtractionResult(parsed=parsed, prompt=prompt_record, raw_response=raw_response)
