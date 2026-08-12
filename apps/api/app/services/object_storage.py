from __future__ import annotations

from functools import lru_cache
import re
from typing import Protocol
from urllib.parse import urlsplit

from botocore.exceptions import ClientError

from app.config import get_settings


def _s3_client_options(settings) -> dict[str, object]:
    from botocore.config import Config

    options: dict[str, object] = {
        "region_name": settings.s3_region,
        "config": Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.s3_force_path_style else "auto"},
        ),
    }
    if settings.s3_access_key_id and settings.s3_secret_access_key:
        options.update(
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )
    return options


class ObjectStorage(Protocol):
    def put_private_object(self, *, key: str, body: bytes, content_type: str) -> None: ...

    def signed_download_url(
        self, *, key: str, filename: str, content_type: str, expires_in: int
    ) -> str: ...

    def delete_object(self, *, key: str) -> None: ...

    def assert_private_bucket(self) -> None: ...


class S3ObjectStorage:
    def __init__(self) -> None:
        import boto3

        settings = get_settings()
        self.bucket = settings.s3_bucket_name
        self.encryption = settings.s3_server_side_encryption
        client_options = _s3_client_options(settings)
        self.client = boto3.client("s3", endpoint_url=settings.s3_endpoint_url, **client_options)
        self.signing_client = boto3.client(
            "s3",
            endpoint_url=settings.effective_s3_public_endpoint_url,
            **client_options,
        )

    def put_private_object(self, *, key: str, body: bytes, content_type: str) -> None:
        _validate_object_key(key)
        arguments: dict[str, object] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": body,
            "ContentType": content_type,
            "CacheControl": "private, no-store",
        }
        if self.encryption:
            arguments["ServerSideEncryption"] = self.encryption
        self.client.put_object(**arguments)

    def assert_private_bucket(self) -> None:
        try:
            public = self.client.get_public_access_block(Bucket=self.bucket)["PublicAccessBlockConfiguration"]
        except ClientError as exc:
            if not self._uses_internal_minio() or not _is_s3_not_implemented(exc):
                raise
            self._assert_minio_bucket_has_no_policy()
            self._assert_encryption_policy()
            return
        required = {"BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"}
        if not all(public.get(key) is True for key in required):
            raise RuntimeError("Object-storage public access block is incomplete")
        status = self.client.get_bucket_policy_status(Bucket=self.bucket).get("PolicyStatus", {})
        if status.get("IsPublic") is not False:
            raise RuntimeError("Object-storage bucket policy is public or unverifiable")
        self._assert_encryption_policy()

    def _uses_internal_minio(self) -> bool:
        settings = get_settings()
        endpoint = urlsplit(settings.s3_endpoint_url)
        return (
            settings.environment == "staging"
            and endpoint.scheme == "http"
            and endpoint.hostname == "object-storage"
            and endpoint.port == 9000
        )

    def _assert_minio_bucket_has_no_policy(self) -> None:
        try:
            self.client.get_bucket_policy(Bucket=self.bucket)
        except ClientError as exc:
            if _is_missing_bucket_policy(exc):
                return
            raise RuntimeError("Object-storage bucket policy is public or unverifiable") from exc
        raise RuntimeError("Object-storage bucket policy is public or unverifiable")

    def _assert_encryption_policy(self) -> None:
        if self.encryption is None:
            return
        rules = self.client.get_bucket_encryption(Bucket=self.bucket)["ServerSideEncryptionConfiguration"]["Rules"]
        algorithms = {rule.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") for rule in rules}
        if self.encryption not in algorithms:
            raise RuntimeError("Object-storage default encryption does not match policy")

    def signed_download_url(
        self, *, key: str, filename: str, content_type: str, expires_in: int
    ) -> str:
        _validate_object_key(key)
        if not filename or any(value in filename for value in {'"', "\r", "\n", "/", "\\"}):
            raise ValueError("download filename is invalid")
        if not content_type or any(value in content_type for value in ("\r", "\n")):
            raise ValueError("download content type is invalid")
        if expires_in < 60 or expires_in > 900:
            raise ValueError("signed URL lifetime is outside the permitted range")
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
        _validate_object_key(key)
        self.client.delete_object(Bucket=self.bucket, Key=key)


_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,1023}$")


def _validate_object_key(key: str) -> None:
    if not _SAFE_KEY.fullmatch(key) or ".." in key.split("/") or "//" in key:
        raise ValueError("object-storage key is invalid")


def _is_s3_not_implemented(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "NotImplemented"


def _is_missing_bucket_policy(exc: ClientError) -> bool:
    return exc.response.get("Error", {}).get("Code") == "NoSuchBucketPolicy"


@lru_cache
def get_object_storage() -> ObjectStorage:
    return S3ObjectStorage()
