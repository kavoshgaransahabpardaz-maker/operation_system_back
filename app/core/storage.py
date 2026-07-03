import uuid
from typing import BinaryIO

import boto3
from botocore.config import Config

from app.core.config import settings

_s3 = boto3.client(
    "s3",
    endpoint_url=settings.S3_ENDPOINT_URL,
    aws_access_key_id=settings.S3_ACCESS_KEY_ID,
    aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
    region_name=settings.S3_REGION,
    config=Config(signature_version="s3v4"),
)


def _key(org_id: str, filename: str) -> str:
    unique = uuid.uuid4().hex
    return f"orgs/{org_id}/documents/{unique}/{filename}"


def upload_file(file_obj: BinaryIO, org_id: str, filename: str, content_type: str) -> str:
    key = _key(org_id, filename)
    _s3.upload_fileobj(
        file_obj,
        settings.S3_BUCKET_NAME,
        key,
        ExtraArgs={"ContentType": content_type},
    )
    return key


def upload_bytes(data: bytes, org_id: str, filename: str, content_type: str) -> str:
    import io
    return upload_file(io.BytesIO(data), org_id, filename, content_type)


def download_bytes(file_key: str) -> bytes:
    response = _s3.get_object(Bucket=settings.S3_BUCKET_NAME, Key=file_key)
    return response["Body"].read()


def get_presigned_url(file_key: str, expires_in: int = 3600) -> str:
    return _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.S3_BUCKET_NAME, "Key": file_key},
        ExpiresIn=expires_in,
    )


def delete_file(file_key: str) -> None:
    _s3.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=file_key)


def ensure_bucket() -> None:
    existing = [b["Name"] for b in _s3.list_buckets().get("Buckets", [])]
    if settings.S3_BUCKET_NAME not in existing:
        _s3.create_bucket(Bucket=settings.S3_BUCKET_NAME)
