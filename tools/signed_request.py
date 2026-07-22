#!/usr/bin/env python3
"""从只读 secret file 生成短时 HMAC 签名并调用管理 API。"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--method", default="POST", choices=("POST", "PUT", "DELETE"))
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--reason", required=True)
    parser.add_argument("--json", default="{}", dest="json_body")
    return parser.parse_args()


def _target(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("absolute_http_url_required")
    if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("plain_http_is_only_allowed_for_loopback")
    return parsed.path + (f"?{parsed.query}" if parsed.query else "")


def main() -> None:
    args = _arguments()
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("token_file_is_missing_or_too_short")
    parsed_body = json.loads(args.json_body)
    body = json.dumps(
        parsed_body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    message = "\n".join(
        (
            "v1",
            timestamp,
            nonce,
            args.method,
            _target(args.url),
            hashlib.sha256(body).hexdigest(),
            args.idempotency_key,
            hashlib.sha256(args.reason.encode()).hexdigest(),
        )
    ).encode()
    signature = hmac.new(token.encode(), message, hashlib.sha256).hexdigest()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Idempotency-Key": args.idempotency_key,
        "X-Change-Reason": args.reason,
        "X-Request-Timestamp": timestamp,
        "X-Request-Nonce": nonce,
        "X-Request-Signature": signature,
    }
    request = urllib.request.Request(
        args.url,
        data=body,
        headers=headers,
        method=args.method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        raise SystemExit(exc.code) from exc


if __name__ == "__main__":
    main()
