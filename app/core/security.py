import hashlib
import secrets

API_KEY_PREFIX = "ie_"


def generate_api_key() -> str:
    """Generate a new raw API key. Only ever returned to the caller once —
    the server stores just its hash (see hash_api_key), so a leaked database
    dump doesn't expose usable credentials.
    """
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode()).hexdigest()
