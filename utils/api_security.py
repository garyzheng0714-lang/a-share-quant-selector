"""管理 API 的 Bearer Token 认证与最小角色权限。

系统不使用 Cookie 传递管理身份。生产必须通过环境变量或 Docker
secret file 提供长度足够的 token；缺少配置时写请求 fail closed。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Callable, TypeVar

from flask import g, jsonify, request


logger = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable)
ROLE_RANK = {"viewer": 0, "publisher": 1, "admin": 2}
TOKEN_ENV = {
    "viewer": "QUANT_VIEWER_TOKEN",
    "publisher": "QUANT_PUBLISHER_TOKEN",
    "admin": "QUANT_ADMIN_TOKEN",
}
MIN_TOKEN_LENGTH = 32
SIGNATURE_VERSION = "v1"
_NONCE_RE = re.compile(r"^[A-Za-z0-9._~-]{16,128}$")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _request_id() -> str:
    value = (
        getattr(g, "request_id", None)
        or request.headers.get("X-Request-ID", "").strip()
    )
    if not value:
        value = uuid.uuid4().hex
    g.request_id = value[:128]
    return g.request_id


def _audit(
    actor: str, role: str | None, outcome: str, required_role: str, **metadata
) -> bool:
    try:
        from utils.operations_store import record_audit

        record_audit(
            actor=actor,
            role=role,
            action=f"authorize:{required_role}",
            outcome=outcome,
            request_id=_request_id(),
            source_ip=request.remote_addr,
            method=request.method,
            path=request.path,
            change_reason=request.headers.get("X-Change-Reason"),
            metadata=metadata,
        )
        return True
    except Exception as exc:
        logger.error("security audit write failed: %s", exc)
        return False


@dataclass(frozen=True)
class Principal:
    principal_id: str
    role: str
    token_fingerprint: str


def _read_secret(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    path_value = os.environ.get(f"{name}_FILE", "").strip()
    if not path_value:
        return None
    try:
        return Path(path_value).read_text(encoding="utf-8").strip() or None
    except OSError:
        logger.error("Cannot read secret file configured by %s_FILE", name)
        return None


def configured_principals() -> list[tuple[Principal, str]]:
    principals = []
    seen = set()
    for role, env_name in TOKEN_ENV.items():
        token = _read_secret(env_name)
        if token is None:
            continue
        if len(token) < MIN_TOKEN_LENGTH:
            logger.error(
                "%s is shorter than %d characters and is ignored",
                env_name,
                MIN_TOKEN_LENGTH,
            )
            continue
        fingerprint = hashlib.sha256(token.encode()).hexdigest()[:16]
        if fingerprint in seen:
            logger.error("Authentication tokens must be distinct; duplicate ignored")
            continue
        seen.add(fingerprint)
        principals.append(
            (Principal(f"{role}:{fingerprint}", role, fingerprint), token)
        )
    return principals


def _signature_message(timestamp: str, nonce: str) -> bytes:
    """绑定请求路径、内容、幂等键和变更原因的签名原文。"""
    body_hash = hashlib.sha256(request.get_data(cache=True)).hexdigest()
    reason_hash = hashlib.sha256(
        request.headers.get("X-Change-Reason", "").encode()
    ).hexdigest()
    target = (
        request.full_path[:-1] if request.full_path.endswith("?") else request.full_path
    )
    fields = (
        SIGNATURE_VERSION,
        timestamp,
        nonce,
        request.method.upper(),
        target,
        body_hash,
        request.headers.get("Idempotency-Key", ""),
        reason_hash,
    )
    return "\n".join(fields).encode()


def _verify_write_signature(principal: Principal, token: str) -> tuple | None:
    timestamp = request.headers.get("X-Request-Timestamp", "").strip()
    nonce = request.headers.get("X-Request-Nonce", "").strip()
    supplied = request.headers.get("X-Request-Signature", "").strip().lower()
    if not timestamp or not nonce or not supplied:
        return jsonify({"success": False, "error": "request_signature_required"}), 401
    try:
        epoch = int(timestamp)
    except ValueError:
        epoch = 0
    try:
        configured_ttl = int(
            os.environ.get("QUANT_REQUEST_SIGNATURE_TTL_SECONDS", "300")
        )
    except ValueError:
        configured_ttl = 300
    ttl = min(max(configured_ttl, 30), 900)
    now = int(time.time())
    if abs(now - epoch) > ttl:
        return jsonify({"success": False, "error": "request_signature_expired"}), 401
    if not _NONCE_RE.fullmatch(nonce):
        return jsonify({"success": False, "error": "request_nonce_invalid"}), 401
    if not re.fullmatch(r"[0-9a-f]{64}", supplied):
        return jsonify({"success": False, "error": "request_signature_required"}), 401
    expected = hmac.new(
        token.encode(),
        _signature_message(timestamp, nonce),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(supplied, expected):
        return jsonify({"success": False, "error": "request_signature_invalid"}), 401
    try:
        from utils.operations_store import claim_request_nonce

        expires_at = datetime.fromtimestamp(epoch, timezone.utc) + timedelta(
            seconds=ttl
        )
        claimed = claim_request_nonce(
            principal.principal_id,
            nonce,
            expires_at=expires_at.isoformat(timespec="seconds"),
        )
    except Exception as exc:
        logger.error("request nonce store failed closed: %s", exc)
        return jsonify(
            {"success": False, "error": "request_signature_store_unavailable"}
        ), 503
    if not claimed:
        return jsonify({"success": False, "error": "request_replay_detected"}), 409
    return None


def authenticate_request(required_role: str) -> tuple[Principal | None, tuple | None]:
    if required_role not in ROLE_RANK:
        raise ValueError(f"unknown role: {required_role}")
    principals = configured_principals()
    if not principals:
        return None, (
            jsonify({"success": False, "error": "admin_auth_not_configured"}),
            503,
        )
    header = request.headers.get("Authorization", "")
    scheme, _, supplied = header.partition(" ")
    if scheme.lower() != "bearer" or not supplied:
        response = jsonify({"success": False, "error": "authentication_required"})
        response.headers["WWW-Authenticate"] = "Bearer"
        return None, (response, 401)
    matched = None
    matched_token = None
    for principal, expected in principals:
        if hmac.compare_digest(supplied, expected):
            matched = principal
            matched_token = expected
    if matched is None:
        return None, (jsonify({"success": False, "error": "invalid_credentials"}), 401)
    if ROLE_RANK[matched.role] < ROLE_RANK[required_role]:
        return None, (jsonify({"success": False, "error": "insufficient_role"}), 403)
    if request.method not in SAFE_METHODS:
        signature_error = _verify_write_signature(matched, matched_token or "")
        if signature_error is not None:
            return None, signature_error
    return matched, None


def require_role(role: str) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapped(*args, **kwargs):
            principal, error = authenticate_request(role)
            if error is not None:
                if request.method not in SAFE_METHODS:
                    _audit("anonymous", None, "denied", role)
                return error
            assert principal is not None
            g.auth_principal = principal
            if request.method in SAFE_METHODS:
                return func(*args, **kwargs)
            try:
                from utils.operations_store import allow_rate

                limit = int(os.environ.get("QUANT_WRITE_RATE_LIMIT_PER_MINUTE", "30"))
                allowed = allow_rate(
                    f"{principal.principal_id}:{request.path}",
                    limit=max(1, limit),
                )
            except Exception as exc:
                logger.error("rate limiter failed closed: %s", exc)
                allowed = False
            if not allowed:
                _audit(principal.principal_id, principal.role, "rate_limited", role)
                return jsonify({"success": False, "error": "rate_limit_exceeded"}), 429
            if not _audit(
                principal.principal_id,
                principal.role,
                "authorized",
                role,
                endpoint=request.endpoint,
            ):
                return jsonify(
                    {"success": False, "error": "security_audit_unavailable"}
                ), 503
            response = func(*args, **kwargs)
            status = (
                response[1]
                if isinstance(response, tuple) and len(response) > 1
                else 200
            )
            _audit(
                principal.principal_id,
                principal.role,
                "allowed" if int(status) < 400 else "endpoint_rejected",
                role,
                response_status=int(status),
            )
            return response

        wrapped.required_role = role  # type: ignore[attr-defined]
        return wrapped  # type: ignore[return-value]

    return decorator
