from functools import lru_cache
from typing import Literal, Optional
import os

from pydantic import BaseModel, Field, computed_field


class UploadStorageSettings(BaseModel):
    """Runtime configuration for user-generated upload storage."""

    mode: Literal["local", "oss"] = Field(default="local")
    public_base_url: Optional[str] = None
    local_root: str = Field(default="/app/data/uploads")

    oss_bucket: Optional[str] = None
    oss_endpoint: str = Field(default="oss-cn-hangzhou.aliyuncs.com")
    oss_region: str = Field(default="cn-hangzhou")
    oss_access_key_id: Optional[str] = None
    oss_access_key_secret: Optional[str] = None
    oss_security_token: Optional[str] = None
    oss_cache_control: str = Field(default="public,max-age=2592000")
    oss_sse: Optional[str] = Field(default="AES256")

    @computed_field
    @property
    def is_oss_ready(self) -> bool:
        return all(
            [
                self.mode == "oss",
                self.oss_bucket,
                self.oss_bucket != "your-bucket-name",
                self.oss_endpoint,
                self.oss_access_key_id,
                self.oss_access_key_secret,
            ]
        )

    @computed_field
    @property
    def is_cdn_ready(self) -> bool:
        return bool(self.public_base_url)


@lru_cache(maxsize=1)
def get_upload_storage_settings() -> UploadStorageSettings:
    return UploadStorageSettings(
        mode=os.getenv("UPLOAD_STORAGE_MODE", "local").strip().lower(),
        public_base_url=(os.getenv("UPLOAD_PUBLIC_BASE_URL") or "").strip().rstrip("/") or None,
        local_root=os.getenv("UPLOAD_STORAGE_LOCAL_ROOT", "/app/data/uploads"),
        oss_bucket=(os.getenv("UPLOAD_STORAGE_OSS_BUCKET") or "").strip() or None,
        oss_endpoint=os.getenv("UPLOAD_STORAGE_OSS_ENDPOINT", "oss-cn-hangzhou.aliyuncs.com").strip(),
        oss_region=os.getenv("UPLOAD_STORAGE_OSS_REGION", "cn-hangzhou").strip(),
        oss_access_key_id=(os.getenv("UPLOAD_STORAGE_OSS_ACCESS_KEY_ID") or "").strip() or None,
        oss_access_key_secret=(os.getenv("UPLOAD_STORAGE_OSS_ACCESS_KEY_SECRET") or "").strip() or None,
        oss_security_token=(os.getenv("UPLOAD_STORAGE_OSS_SECURITY_TOKEN") or "").strip() or None,
        oss_cache_control=os.getenv("UPLOAD_STORAGE_OSS_CACHE_CONTROL", "public,max-age=2592000").strip(),
        oss_sse=(os.getenv("UPLOAD_STORAGE_OSS_SSE") or "").strip() or None,
    )
