from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.llm.base import LLMClient

_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqClient(LLMClient):
    """Groq's API is OpenAI-compatible, so the official openai SDK works
    unmodified against it — just point base_url at Groq and use a Groq
    model name. Swapping providers later means writing one more class
    like this one, not touching any calling code.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncOpenAI(api_key=settings.groq_api_key, base_url=_GROQ_BASE_URL)
        self._model = settings.groq_model

    async def complete_json(self, *, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        return response.choices[0].message.content or ""
