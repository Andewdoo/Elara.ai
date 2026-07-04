"""Bounded upload validation; uploaded bytes are never interpreted or executed by the API."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


class UploadValidationError(ValueError):
    pass


_ALLOWED = {
    "application/pdf": (".pdf",),
    "text/plain": (".txt",),
}
_EXECUTABLE_SIGNATURES = (
    b"MZ",
    b"\x7fELF",
    b"PK\x03\x04",
    b"#!",
    b"\xfe\xed\xfa\xce",
    b"\xcf\xfa\xed\xfe",
)


@dataclass(frozen=True, slots=True)
class ValidatedUpload:
    filename: str
    content_type: str
    body: bytes
    content_hash: str


def validate_upload(
    *, filename: str | None, content_type: str | None, body: bytes, max_bytes: int
) -> ValidatedUpload:
    original_name = filename or ""
    safe_name = Path(original_name).name
    normalized_type = (content_type or "").split(";", 1)[0].strip().casefold()
    if (
        not safe_name
        or safe_name != original_name
        or any(separator in original_name for separator in ("/", "\\"))
        or any(ord(character) < 32 or ord(character) == 127 for character in original_name)
        or len(safe_name) > 255
    ):
        raise UploadValidationError("Upload filename is invalid")
    if normalized_type not in _ALLOWED:
        raise UploadValidationError("Upload content type is not supported")
    if Path(safe_name).suffix.casefold() not in _ALLOWED[normalized_type]:
        raise UploadValidationError("Upload extension does not match its content type")
    if not body:
        raise UploadValidationError("Upload is empty")
    if len(body) > max_bytes:
        raise UploadValidationError("Upload exceeds the configured size limit")
    if body.startswith(_EXECUTABLE_SIGNATURES):
        raise UploadValidationError("Executable or archive uploads are not supported")
    if normalized_type == "application/pdf" and not body.startswith(b"%PDF-"):
        raise UploadValidationError("PDF signature does not match its content type")
    if normalized_type == "text/plain":
        try:
            decoded = body.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise UploadValidationError("Plain-text uploads must be valid UTF-8") from exc
        if any(
            ord(character) < 32 and character not in {"\t", "\n", "\r"}
            for character in decoded
        ):
            raise UploadValidationError("Binary control characters are not supported as text")
    return ValidatedUpload(
        filename=safe_name,
        content_type=normalized_type,
        body=body,
        content_hash=hashlib.sha256(body).hexdigest(),
    )


__all__ = ["UploadValidationError", "ValidatedUpload", "validate_upload"]
