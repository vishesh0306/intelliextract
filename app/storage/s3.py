import asyncio

import boto3
from botocore.exceptions import ClientError

from app.storage.base import StorageBackend


class S3Storage(StorageBackend):
    def __init__(self, bucket_name: str, region: str | None = None) -> None:
        self._bucket = bucket_name
        self._client = boto3.client("s3", region_name=region)

    async def save(self, key: str, content: bytes) -> None:
        # boto3 is sync-only; run it off the event loop rather than block it.
        await asyncio.to_thread(self._client.put_object, Bucket=self._bucket, Key=key, Body=content)

    async def read(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get_object, key)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._head_object, key)

    def _get_object(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=key)
        return response["Body"].read()

    def _head_object(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError:
            return False
