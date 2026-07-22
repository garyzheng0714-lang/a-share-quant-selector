import hashlib
import hmac
import os
import sqlite3
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch

from flask import Flask, jsonify

from utils.api_security import require_role
from utils.operations_store import enqueue_task, init_operations_db, record_alert
from utils.task_submission import submit_task
from views.operations_api import operations_bp


ADMIN = "a" * 40
PUBLISHER = "p" * 40
VIEWER = "v" * 40


class ApiSecurityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {"QUANT_OPERATIONS_DB": os.path.join(self.tmp.name, "operations.db")},
            clear=True,
        )
        self.env.start()
        init_operations_db()
        app = Flask(__name__)

        @app.post("/admin")
        @require_role("admin")
        def admin():
            return jsonify({"ok": True})

        @app.post("/publish")
        @require_role("publisher")
        def publish():
            return jsonify({"ok": True})

        @app.get("/read")
        @require_role("viewer")
        def read():
            return jsonify({"ok": True})

        @app.post("/submit")
        @require_role("admin")
        def submit():
            return submit_task("daily_market_ingestion")

        app.register_blueprint(operations_bp)

        self.client = app.test_client()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    @staticmethod
    def _signed_headers(
        token: str,
        path: str,
        *,
        nonce: str | None = None,
        timestamp: int | None = None,
        body: bytes = b"",
        idempotency_key: str = "",
        reason: str = "",
    ) -> dict[str, str]:
        timestamp_text = str(timestamp or int(time.time()))
        nonce = nonce or uuid.uuid4().hex
        message = "\n".join(
            (
                "v1",
                timestamp_text,
                nonce,
                "POST",
                path,
                hashlib.sha256(body).hexdigest(),
                idempotency_key,
                hashlib.sha256(reason.encode()).hexdigest(),
            )
        ).encode()
        signature = hmac.new(token.encode(), message, hashlib.sha256).hexdigest()
        return {
            "Authorization": f"Bearer {token}",
            "X-Request-Timestamp": timestamp_text,
            "X-Request-Nonce": nonce,
            "X-Request-Signature": signature,
        }

    def test_write_fails_closed_when_auth_is_not_configured(self):
        response = self.client.post("/admin")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error"], "admin_auth_not_configured")

    def test_missing_and_invalid_credentials_are_rejected(self):
        with patch.dict(os.environ, {"QUANT_ADMIN_TOKEN": ADMIN}):
            missing = self.client.post("/admin")
            invalid = self.client.post(
                "/admin",
                headers={"Authorization": "Bearer " + "x" * 40},
            )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid.status_code, 401)

    def test_role_hierarchy_is_enforced(self):
        env = {
            "QUANT_ADMIN_TOKEN": ADMIN,
            "QUANT_PUBLISHER_TOKEN": PUBLISHER,
            "QUANT_VIEWER_TOKEN": VIEWER,
        }
        with patch.dict(os.environ, env):
            viewer = self.client.post(
                "/publish",
                headers=self._signed_headers(VIEWER, "/publish"),
            )
            publisher = self.client.post(
                "/publish",
                headers=self._signed_headers(PUBLISHER, "/publish"),
            )
            admin = self.client.post(
                "/publish",
                headers=self._signed_headers(ADMIN, "/publish"),
            )
        self.assertEqual(viewer.status_code, 403)
        self.assertEqual(publisher.status_code, 200)
        self.assertEqual(admin.status_code, 200)

    def test_short_token_is_not_accepted_as_configuration(self):
        with patch.dict(os.environ, {"QUANT_ADMIN_TOKEN": "short"}):
            response = self.client.post(
                "/admin",
                headers={"Authorization": "Bearer short"},
            )
        self.assertEqual(response.status_code, 503)

    def test_valid_token_without_request_signature_is_rejected(self):
        with patch.dict(os.environ, {"QUANT_ADMIN_TOKEN": ADMIN}):
            response = self.client.post(
                "/admin", headers={"Authorization": f"Bearer {ADMIN}"}
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"], "request_signature_required")

    def test_signed_request_nonce_cannot_be_replayed(self):
        headers = self._signed_headers(ADMIN, "/admin")
        with patch.dict(os.environ, {"QUANT_ADMIN_TOKEN": ADMIN}):
            first = self.client.post("/admin", headers=headers)
            replay = self.client.post("/admin", headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(replay.json["error"], "request_replay_detected")

    def test_signature_binds_change_reason(self):
        headers = self._signed_headers(ADMIN, "/admin", reason="approved change")
        headers["X-Change-Reason"] = "tampered change"
        with patch.dict(os.environ, {"QUANT_ADMIN_TOKEN": ADMIN}):
            response = self.client.post("/admin", headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"], "request_signature_invalid")

    def test_expired_signature_is_rejected(self):
        headers = self._signed_headers(
            ADMIN,
            "/admin",
            timestamp=int(time.time()) - 301,
        )
        with patch.dict(os.environ, {"QUANT_ADMIN_TOKEN": ADMIN}):
            response = self.client.post("/admin", headers=headers)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"], "request_signature_expired")

    def test_authorized_write_fails_closed_when_audit_store_is_unavailable(self):
        headers = self._signed_headers(ADMIN, "/admin")
        with (
            patch.dict(os.environ, {"QUANT_ADMIN_TOKEN": ADMIN}),
            patch(
                "utils.operations_store.record_audit",
                side_effect=OSError("audit disk unavailable"),
            ),
        ):
            response = self.client.post("/admin", headers=headers)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error"], "security_audit_unavailable")

    def test_authenticated_get_is_database_read_only(self):
        database = os.environ["QUANT_OPERATIONS_DB"]
        with sqlite3.connect(database) as connection:
            before = {
                "audit": connection.execute(
                    "SELECT COUNT(*) FROM audit_events"
                ).fetchone()[0],
                "rate": connection.execute(
                    "SELECT COUNT(*) FROM rate_limits"
                ).fetchone()[0],
                "nonce": connection.execute(
                    "SELECT COUNT(*) FROM request_nonces"
                ).fetchone()[0],
            }

        with patch.dict(os.environ, {"QUANT_VIEWER_TOKEN": VIEWER}):
            allowed = self.client.get(
                "/read", headers={"Authorization": f"Bearer {VIEWER}"}
            )
            denied = self.client.get("/read")

        with sqlite3.connect(database) as connection:
            after = {
                "audit": connection.execute(
                    "SELECT COUNT(*) FROM audit_events"
                ).fetchone()[0],
                "rate": connection.execute(
                    "SELECT COUNT(*) FROM rate_limits"
                ).fetchone()[0],
                "nonce": connection.execute(
                    "SELECT COUNT(*) FROM request_nonces"
                ).fetchone()[0],
            }

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(after, before)

    def test_alert_feed_requires_viewer_and_returns_persisted_event(self):
        alert_id = record_alert(
            severity="critical",
            alert_type="upstream_data_unavailable",
            source="test",
            subject_id="snapshot-1",
            message="all upstream sources failed",
            details={"reason": "all_sources_failed"},
            dedup_key="snapshot-1:all_sources_failed",
        )
        database = os.environ["QUANT_OPERATIONS_DB"]
        with sqlite3.connect(database) as connection:
            before = tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "alert_events",
                    "audit_events",
                    "rate_limits",
                    "request_nonces",
                )
            )

        with patch.dict(os.environ, {"QUANT_VIEWER_TOKEN": VIEWER}):
            allowed = self.client.get(
                "/api/alerts", headers={"Authorization": f"Bearer {VIEWER}"}
            )
            denied = self.client.get("/api/alerts")

        with sqlite3.connect(database) as connection:
            after = tuple(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in (
                    "alert_events",
                    "audit_events",
                    "rate_limits",
                    "request_nonces",
                )
            )

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json["data"]["alerts"][0]["alert_id"], alert_id)
        self.assertEqual(allowed.json["data"]["summary"]["critical"], 1)
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(after, before)

    def test_admin_can_cancel_queued_task_with_signed_reason(self):
        task, _ = enqueue_task(
            "daily_market_ingestion",
            "cancel-api-task",
            requested_by="test",
        )
        path = f"/api/tasks/{task['task_id']}/cancel"
        reason = "operator cancelled obsolete request"
        idempotency_key = f"cancel:{task['task_id']}"
        headers = self._signed_headers(
            ADMIN,
            path,
            idempotency_key=idempotency_key,
            reason=reason,
        )
        headers["Idempotency-Key"] = idempotency_key
        headers["X-Change-Reason"] = reason

        with patch.dict(os.environ, {"QUANT_ADMIN_TOKEN": ADMIN}):
            response = self.client.post(path, headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json["cancelled"])
        self.assertEqual(response.json["task"]["status"], "cancelled")

    def test_task_submission_returns_503_when_queue_is_full(self):
        enqueue_task(
            "daily_market_ingestion",
            "existing-capacity-task",
            requested_by="test",
        )
        reason = "capacity behavior test"
        idempotency_key = "new-capacity-task"
        headers = self._signed_headers(
            ADMIN,
            "/submit",
            body=b"{}",
            idempotency_key=idempotency_key,
            reason=reason,
        )
        headers["Idempotency-Key"] = idempotency_key
        headers["X-Change-Reason"] = reason

        with patch.dict(
            os.environ,
            {
                "QUANT_ADMIN_TOKEN": ADMIN,
                "QUANT_MAX_PENDING_TASKS": "1",
            },
        ):
            response = self.client.post(
                "/submit", headers=headers, data=b"{}", content_type="application/json"
            )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error"], "task_queue_capacity_exceeded")
        self.assertEqual(response.json["pending"], 1)

    def test_every_state_changing_route_is_protected_or_permanently_disabled(self):
        from web_server import app

        unprotected = []
        permanently_disabled = {"insight.api_generate_daily_pick"}
        for rule in app.url_map.iter_rules():
            if not ({"POST", "PUT", "PATCH", "DELETE"} & set(rule.methods or ())):
                continue
            view = app.view_functions[rule.endpoint]
            if rule.endpoint not in permanently_disabled and not getattr(
                view, "required_role", None
            ):
                unprotected.append(f"{sorted(rule.methods)} {rule.rule}")
        self.assertEqual(unprotected, [])
        self.assertNotIn(
            "/api/scheduler/start", {rule.rule for rule in app.url_map.iter_rules()}
        )
        self.assertNotIn(
            "/api/scheduler/stop", {rule.rule for rule in app.url_map.iter_rules()}
        )


if __name__ == "__main__":
    unittest.main()
