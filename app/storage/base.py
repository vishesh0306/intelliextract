from abc import ABC, abstractmethod


class StorageBackend(ABC):
    """Storage interface so the API/worker never depends on where bytes
    actually live — local disk in dev, S3 in prod, selected at startup by
    STORAGE_BACKEND.
    """

    @abstractmethod
    async def save(self, key: str, content: bytes) -> None: ...

    @abstractmethod
    async def read(self, key: str) -> bytes: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...
