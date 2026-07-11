from functools import lru_cache

from app.services.llm.base import LLMClient
from app.services.llm.groq_client import GroqClient


@lru_cache
def get_llm_client() -> LLMClient:
    return GroqClient()
