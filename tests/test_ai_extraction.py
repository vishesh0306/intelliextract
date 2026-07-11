import json

from app.schemas.invoice import InvoiceFields
from app.services import ai_extraction

VALID_INVOICE_JSON = json.dumps(
    {
        "invoice_number": "INV-001",
        "date": "2026-01-15",
        "vendor": "Acme Corp",
        "line_items": [
            {"description": "Widget", "quantity": 2, "unit_price": 10.0, "amount": 20.0}
        ],
        "total": 20.0,
    }
)


class _FakeLLMClient:
    def __init__(self, response: str) -> None:
        self._response = response

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        return self._response


async def test_extract_invoice_fields_parses_valid_json(monkeypatch) -> None:
    monkeypatch.setattr(ai_extraction, "get_llm_client", lambda: _FakeLLMClient(VALID_INVOICE_JSON))

    result = await ai_extraction.extract_invoice_fields("some raw invoice text")

    assert isinstance(result.parsed, InvoiceFields)
    assert result.parsed.invoice_number == "INV-001"
    assert result.parsed.line_items[0].description == "Widget"
    assert result.raw_response == VALID_INVOICE_JSON
    assert "some raw invoice text" in result.prompt


async def test_extract_invoice_fields_handles_malformed_json(monkeypatch) -> None:
    monkeypatch.setattr(ai_extraction, "get_llm_client", lambda: _FakeLLMClient("not json at all"))

    result = await ai_extraction.extract_invoice_fields("some raw invoice text")

    assert result.parsed is None
    assert result.raw_response == "not json at all"


async def test_extract_invoice_fields_handles_missing_required_field(monkeypatch) -> None:
    incomplete_json = json.dumps({"invoice_number": "INV-002"})
    monkeypatch.setattr(ai_extraction, "get_llm_client", lambda: _FakeLLMClient(incomplete_json))

    result = await ai_extraction.extract_invoice_fields("some raw invoice text")

    assert result.parsed is None
