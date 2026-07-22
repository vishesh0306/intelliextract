import json
from dataclasses import dataclass
from typing import Any

from app.services.llm.factory import get_llm_client

_FIELDS_SYSTEM_PROMPT = """You are a precise document data extraction engine.

Extract the following fields from the raw text of a document and respond
with ONLY a single JSON object — no markdown fences, no commentary — using
EXACTLY these strings as the JSON keys, in this order: {field_list}

Rules:
- If a field's value cannot be found in the text, set it to null. Never
  guess or invent a value that isn't actually in the text.
- Include every requested key, even when its value is null.
- Use plain strings or numbers as values, not nested objects, unless a
  field name clearly implies a list (e.g. "skills", "line_items").
"""

_OPEN_ENDED_SYSTEM_PROMPT = """You are a precise document data extraction engine.

Read the raw text of a document and respond with ONLY a single JSON
object — no markdown fences, no commentary — containing whatever
key-value fields best represent the important structured information in
this document (for an invoice: things like invoice_number, vendor,
total; for a resume: things like name, skills, education). Choose clear,
descriptive, snake_case keys yourself based on what this specific
document actually contains. Never invent information that isn't in the
text.
"""

_RETRY_NOTE = (
    "Your previous response was not valid JSON. Respond again with ONLY "
    "the JSON object — no markdown fences, no commentary, no leading or "
    "trailing text."
)


@dataclass
class QueryExtractionResult:
    result: dict[str, Any]
    prompt: str
    raw_response: str
    parse_error: str | None = None


async def run_document_query(raw_text: str, fields: list[str] | None) -> QueryExtractionResult:
    """One LLM call against a document's already-extracted text, asking
    for either specific fields (keys echo exactly what was requested) or,
    if none were given, whatever fields the model judges relevant.

    No fixed schema and no business-rule validation here — unlike the
    invoice pipeline, there's no generalizable "does this reconcile" check
    for an arbitrary field on an arbitrary document. The only thing worth
    retrying is "did the model even return valid JSON," so that's the one
    retry this does — a single attempt, not the 3-attempt self-correction
    loop invoices get.
    """
    if fields:
        field_list = ", ".join(f'"{name}"' for name in fields)
        system_prompt = _FIELDS_SYSTEM_PROMPT.format(field_list=field_list)
    else:
        system_prompt = _OPEN_ENDED_SYSTEM_PROMPT

    client = get_llm_client()
    raw_response = await client.complete_json(system_prompt=system_prompt, user_prompt=raw_text)
    result, parse_error = _try_parse(raw_response)

    if parse_error is not None:
        retry_prompt = f"{raw_text}\n\n{_RETRY_NOTE}"
        raw_response = await client.complete_json(
            system_prompt=system_prompt, user_prompt=retry_prompt
        )
        result, parse_error = _try_parse(raw_response)

    prompt_record = json.dumps(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": raw_text},
        ]
    )
    return QueryExtractionResult(
        result=result or {},
        prompt=prompt_record,
        raw_response=raw_response,
        parse_error=parse_error,
    )


def _try_parse(raw_response: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        return None, f"Response was not valid JSON: {exc}"

    if not isinstance(parsed, dict):
        return None, "Response was valid JSON but not a JSON object"

    return parsed, None
