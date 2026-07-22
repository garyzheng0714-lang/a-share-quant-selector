"""生产派生产物的内容摘要。

缓存身份回答“它应该由哪份数据和代码生成”，内容摘要回答
“落盘后的字节约定是否被改过”。两者都通过才能进入生产读取链路。
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from typing import Any


ARTIFACT_HASH_FIELD = "artifact_content_hash"


def artifact_content_hash(payload: Mapping[str, Any]) -> str:
    """计算不包含摘要字段自身的规范 JSON SHA-256。"""
    canonical = dict(payload)
    canonical.pop(ARTIFACT_HASH_FIELD, None)
    raw = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def seal_artifact(payload: Mapping[str, Any]) -> dict[str, Any]:
    """返回带内容摘要的新字典，不修改调用方对象。"""
    sealed = dict(payload)
    sealed[ARTIFACT_HASH_FIELD] = artifact_content_hash(sealed)
    return sealed


def artifact_is_valid(payload: object) -> bool:
    """严格校验派生产物摘要；旧的无摘要缓存一律失效。"""
    if not isinstance(payload, dict):
        return False
    recorded = payload.get(ARTIFACT_HASH_FIELD)
    if not isinstance(recorded, str) or not recorded.startswith("sha256:"):
        return False
    try:
        expected = artifact_content_hash(payload)
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(recorded, expected)
