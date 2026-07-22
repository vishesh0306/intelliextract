import json

from app.services import generic_extraction


class _ScriptedLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, str]] = []

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_prompt": user_prompt})
        return self._responses.pop(0)


def _use_scripted_client(monkeypatch, responses: list[str]) -> _ScriptedLLMClient:
    client = _ScriptedLLMClient(responses)
    monkeypatch.setattr(generic_extraction, "get_llm_client", lambda: client)
    return client


async def test_with_fields_echoes_requested_keys(monkeypatch) -> None:
    response = json.dumps({"vendor_name": "Acme Corp", "total_amount": 1250.0})
    client = _use_scripted_client(monkeypatch, [response])

    outcome = await generic_extraction.run_document_query(
        "some invoice text", fields=["vendor_name", "total_amount"]
    )

    assert outcome.result == {"vendor_name": "Acme Corp", "total_amount": 1250.0}
    assert outcome.parse_error is None
    assert len(client.calls) == 1
    assert '"vendor_name"' in client.calls[0]["system_prompt"]
    assert '"total_amount"' in client.calls[0]["system_prompt"]


async def test_without_fields_uses_open_ended_prompt(monkeypatch) -> None:
    response = json.dumps({"name": "Jane Doe", "skills": ["Python", "SQL"]})
    client = _use_scripted_client(monkeypatch, [response])

    outcome = await generic_extraction.run_document_query("some resume text", fields=None)

    assert outcome.result == {"name": "Jane Doe", "skills": ["Python", "SQL"]}
    assert "choose" in client.calls[0]["system_prompt"].lower()


async def test_retries_once_on_malformed_json_then_succeeds(monkeypatch) -> None:
    valid = json.dumps({"total_amount": 42.0})
    client = _use_scripted_client(monkeypatch, ["not json at all", valid])

    outcome = await generic_extraction.run_document_query(
        "some invoice text", fields=["total_amount"]
    )

    assert outcome.result == {"total_amount": 42.0}
    assert outcome.parse_error is None
    assert len(client.calls) == 2
    assert "not valid JSON" in client.calls[1]["user_prompt"]


async def test_returns_parse_error_after_exhausting_retry(monkeypatch) -> None:
    client = _use_scripted_client(monkeypatch, ["still not json", "nope, also not json"])

    outcome = await generic_extraction.run_document_query(
        "some invoice text", fields=["total_amount"]
    )

    assert outcome.result == {}
    assert outcome.parse_error is not None
    assert len(client.calls) == 2


async def test_non_object_json_is_treated_as_parse_error(monkeypatch) -> None:
    _use_scripted_client(monkeypatch, ["[1, 2, 3]", "[1, 2, 3]"])

    outcome = await generic_extraction.run_document_query("some text", fields=["x"])

    assert outcome.result == {}
    assert outcome.parse_error is not None
