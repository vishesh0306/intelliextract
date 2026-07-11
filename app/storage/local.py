import asyncio
from pathlib import Path

from app.storage.base import StorageBackend


class LocalFilesystemStorage(StorageBackend):
    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    async def save(self, key: str, content: bytes) -> None:
        # File I/O is blocking; run it off the event loop like the S3
        # client call would be (implicitly, via the network) in the other
        # backend, so switching backends doesn't change the concurrency
        # story for callers.
        await asyncio.to_thread(self._write, key, content)

    async def read(self, key: str) -> bytes:
        return await asyncio.to_thread((self._root / key).read_bytes)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(lambda: (self._root / key).exists())

    def _write(self, key: str, content: bytes) -> None:
        path = self._root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
