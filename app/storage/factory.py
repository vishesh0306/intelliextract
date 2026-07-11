from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import StorageBackend
from app.storage.local import LocalFilesystemStorage


@lru_cache
def get_storage_backend() -> StorageBackend:
    settings = get_settings()

    if settings.storage_backend == "s3":
        from app.storage.s3 import S3Storage

        if not settings.s3_bucket_name:
            raise RuntimeError("S3_BUCKET_NAME must be set when STORAGE_BACKEND=s3")
        return S3Storage(bucket_name=settings.s3_bucket_name, region=settings.aws_region)

    return LocalFilesystemStorage(root=settings.local_storage_path)
