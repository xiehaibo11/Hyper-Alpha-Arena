from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Optional
import mimetypes

from config.storage import UploadStorageSettings, get_upload_storage_settings


class UploadStorageError(RuntimeError):
    pass


class UploadStorage:
    def __init__(self, settings: Optional[UploadStorageSettings] = None):
        self.settings = settings or get_upload_storage_settings()

    def save_bytes(
        self,
        object_key: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> str:
        if self.settings.mode == "oss":
            return self._save_oss(object_key, content, content_type)
        return self._save_local(object_key, content)

    def save_fileobj(
        self,
        object_key: str,
        fileobj: BinaryIO,
        content_type: Optional[str] = None,
    ) -> str:
        return self.save_bytes(object_key, fileobj.read(), content_type)

    def _save_local(self, object_key: str, content: bytes) -> str:
        path = self._local_path(object_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return self._public_url(object_key)

    def _save_oss(
        self,
        object_key: str,
        content: bytes,
        content_type: Optional[str],
    ) -> str:
        if not self.settings.is_oss_ready:
            raise UploadStorageError("Aliyun OSS storage is not fully configured")

        try:
            import oss2
        except ImportError as exc:
            raise UploadStorageError("Missing oss2 dependency for Aliyun OSS storage") from exc

        auth = oss2.StsAuth(
            self.settings.oss_access_key_id,
            self.settings.oss_access_key_secret,
            self.settings.oss_security_token,
        ) if self.settings.oss_security_token else oss2.Auth(
            self.settings.oss_access_key_id,
            self.settings.oss_access_key_secret,
        )

        endpoint = self.settings.oss_endpoint
        if not endpoint.startswith(("http://", "https://")):
            endpoint = f"https://{endpoint}"

        bucket = oss2.Bucket(auth, endpoint, self.settings.oss_bucket)
        headers = {
            "Cache-Control": self.settings.oss_cache_control,
            "Content-Type": content_type or self._guess_content_type(object_key),
        }
        if self.settings.oss_sse:
            headers["x-oss-server-side-encryption"] = self.settings.oss_sse

        bucket.put_object(self._clean_key(object_key), content, headers=headers)
        return self._public_url(object_key)

    def _public_url(self, object_key: str) -> str:
        key = self._clean_key(object_key)
        if self.settings.public_base_url:
            return f"{self.settings.public_base_url}/{key}"
        if self.settings.mode == "oss" and self.settings.oss_bucket:
            endpoint = self.settings.oss_endpoint.removeprefix("https://").removeprefix("http://")
            return f"https://{self.settings.oss_bucket}.{endpoint}/{key}"
        return f"/uploads/{key}"

    def _local_path(self, object_key: str) -> Path:
        root = Path(self.settings.local_root).resolve()
        path = (root / self._clean_key(object_key)).resolve()
        if root not in path.parents and path != root:
            raise UploadStorageError("Invalid upload object key")
        return path

    @staticmethod
    def _clean_key(object_key: str) -> str:
        key = object_key.strip().lstrip("/")
        if not key or ".." in key.split("/"):
            raise UploadStorageError("Invalid upload object key")
        return key

    @staticmethod
    def _guess_content_type(object_key: str) -> str:
        return mimetypes.guess_type(object_key)[0] or "application/octet-stream"


def get_upload_storage() -> UploadStorage:
    return UploadStorage()
