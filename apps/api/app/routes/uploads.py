import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthenticatedUser, get_authenticated_bearer
from app.config import Settings, get_settings
from app.database.session import get_db
from app.models import Upload
from app.schemas.verifications import UploadResponse
from app.services.object_storage import ObjectStorage, get_object_storage
from app.services.uploads import UploadValidationError, validate_upload


router = APIRouter(prefix="/v1/uploads", tags=["uploads"])
logger = logging.getLogger(__name__)


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def create_upload(
    file: UploadFile = File(...),
    authenticated: AuthenticatedUser = Depends(get_authenticated_bearer),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    storage: ObjectStorage = Depends(get_object_storage),
) -> UploadResponse:
    body = bytearray()
    while chunk := await file.read(64 * 1024):
        body.extend(chunk)
        if len(body) > settings.upload_max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Upload exceeds the configured size limit",
            )
    try:
        validated = validate_upload(
            filename=file.filename,
            content_type=file.content_type,
            body=bytes(body),
            max_bytes=settings.upload_max_bytes,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc

    upload_id = uuid4()
    suffix = ".pdf" if validated.content_type == "application/pdf" else ".txt"
    object_path = f"uploads/{authenticated.user.id}/{upload_id}/source{suffix}"
    try:
        storage.put_private_object(
            key=object_path,
            body=validated.body,
            content_type=validated.content_type,
        )
    except Exception as exc:
        logger.error("Private upload storage failed for upload %s", upload_id, exc_info=False)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload storage is temporarily unavailable",
        ) from exc
    row = Upload(
        id=upload_id,
        user_id=authenticated.user.id,
        object_path=object_path,
        original_filename=validated.filename,
        content_type=validated.content_type,
        size_bytes=len(validated.body),
        content_hash=validated.content_hash,
    )
    try:
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
        try:
            storage.delete_object(key=object_path)
        except Exception:
            logger.error("Failed to remove uncommitted upload %s", upload_id, exc_info=False)
        raise
    return UploadResponse(
        upload_id=row.id,
        filename=row.original_filename,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        content_hash=row.content_hash,
    )
