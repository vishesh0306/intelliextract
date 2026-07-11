from abc import ABC, abstractmethod


class LLMClient(ABC):
    """Deliberately schema-agnostic: the client's only job is turning a
    prompt into a raw JSON string. Parsing that string against a Pydantic
    schema (and deciding what to do if it doesn't match) is the caller's
    job, not the client's — that keeps the provider swappable without any
    document-type-specific logic leaking into it.
    """

    @abstractmethod
    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str: ...
