from __future__ import annotations

from functools import lru_cache
from typing import Protocol

from app.config import get_settings


class ObjectStorage(Protocol):
    def put_private_object(self, *, key: str, body: bytes, content_type: str) -> None: ...

    def signed_download_url(
        self, *, key: str, filename: str, content_type: str, expires_in: int
    ) -> str: ...

    def delete_object(self, *, key: str) -> None: ...


class S3ObjectStorage:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        settings = get_settings()
        self.bucket = settings.s3_bucket_name
        client_options = {
            "aws_access_key_id": settings.s3_access_key_id,
            "aws_secret_access_key": settings.s3_secret_access_key,
            "region_name": settings.s3_region,
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
            ),
        }
        self.client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url, **client_options)
        self.signing_client = boto3.client(
            "s3",
            endpoint_url=settings.effective_s3_public_endpoint_url,
            **client_options,
        )

    def put_private_object(self, *, key: str, body: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl="private, no-store",
        )

    def signed_download_url(
        self, *, key: str, filename: str, content_type: str, expires_in: int
    ) -> str:
        return str(
            self.signing_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ResponseContentDisposition": f'attachment; filename="{filename}"',
                    "ResponseContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
        )

    def delete_object(self, *, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


@lru_cache
def get_object_storage() -> ObjectStorage:
    return S3ObjectStorage()
