import json

from app.services import ai_extraction, self_correction

VALID_JSON = json.dumps(
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

# Passes schema validation but fails the business rule: 20.0 != 999.0
BAD_TOTAL_JSON = json.dumps(
    {
        "invoice_number": "INV-001",
        "date": "2026-01-15",
        "vendor": "Acme Corp",
        "line_items": [
            {"description": "Widget", "quantity": 2, "unit_price": 10.0, "amount": 20.0}
        ],
        "total": 999.0,
    }
)


class _ScriptedLLMClient:
    """Returns one canned response per call, in order — lets a test drive
    exactly what "the model's 2nd attempt" looks like without a real LLM.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, str]] = []

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return self._responses.pop(0)


def _use_scripted_client(monkeypatch, responses: list[str]) -> _ScriptedLLMClient:
    client = _ScriptedLLMClient(responses)
    monkeypatch.setattr(ai_extraction, "get_llm_client", lambda: client)
    return client


async def test_succeeds_on_first_attempt_no_retry_needed(monkeypatch) -> None:
    client = _use_scripted_client(monkeypatch, [VALID_JSON])

    outcome = await self_correction.run_invoice_self_correction("some invoice text")

    assert outcome.needs_review is False
    assert outcome.fields.invoice_number == "INV-001"
    assert len(outcome.attempts) == 1
    assert len(client.calls) == 1
    assert outcome.confidence_scores == {
        "invoice_number": 0.95,
        "date": 0.95,
        "vendor": 0.95,
        "line_items": 0.95,
        "total": 0.95,
    }


async def test_bad_first_response_triggers_retry_that_succeeds(monkeypatch) -> None:
    """The centerpiece behavior: a business-rule failure on attempt 1
    causes a second LLM call that includes the specific error, and that
    second attempt succeeds.
    """
    client = _use_scripted_client(monkeypatch, [BAD_TOTAL_JSON, VALID_JSON])

    outcome = await self_correction.run_invoice_self_correction("some invoice text")

    assert outcome.needs_review is False
    assert len(outcome.attempts) == 2
    assert len(client.calls) == 2

    # attempt 1 recorded the business-rule failure
    assert outcome.attempts[0].errors[0][0] == "total"

    # attempt 2's prompt told the model what was wrong with attempt 1
    retry_prompt = client.calls[1]["user_prompt"]
    assert "999.00" in retry_prompt
    assert "previous extraction" in retry_prompt.lower()

    # a field implicated by a past failure keeps a lower confidence even
    # though the final attempt succeeded
    assert outcome.confidence_scores["total"] < outcome.confidence_scores["vendor"]


async def test_exhausts_retries_and_lands_on_needs_review(monkeypatch) -> None:
    client = _use_scripted_client(monkeypatch, [BAD_TOTAL_JSON, BAD_TOTAL_JSON, BAD_TOTAL_JSON])

    outcome = await self_correction.run_invoice_self_correction("some invoice text")

    assert outcome.needs_review is True
    assert len(outcome.attempts) == self_correction.MAX_ATTEMPTS
    assert len(client.calls) == self_correction.MAX_ATTEMPTS
    # best-effort fields are still returned for a human reviewer, even
    # though validation never passed
    assert outcome.fields is not None
    assert outcome.fields.invoice_number == "INV-001"
    assert outcome.confidence_scores["total"] < outcome.confidence_scores["vendor"]


async def test_exhausts_retries_with_unparseable_responses_returns_no_fields(monkeypatch) -> None:
    _use_scripted_client(monkeypatch, ["not json", "still not json", "nope"])

    outcome = await self_correction.run_invoice_self_correction("some invoice text")

    assert outcome.needs_review is True
    assert outcome.fields is None
    assert outcome.confidence_scores is None
    assert len(outcome.attempts) == self_correction.MAX_ATTEMPTS
