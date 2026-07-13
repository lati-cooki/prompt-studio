"""Task 19 — cloud_store: the laptop's client for the studio Worker operator
API. A stub HTTP server (http.server in a background thread, the same shape as
the repo's other hub-interaction tests) stands in for the Worker; each test
asserts the client hit the right METHOD + PATH + BODY + BEARER, that a non-2xx
becomes promotion_store.PromotionError(msg, status), that a transport failure
becomes a 502 PromotionError, and that get/list return shapes pass through
untouched.

A final group drives server.py's cloud-mode switch: with STUDIO_CLOUD_BASE_URL
set, a promote / mint / resolve / close routes THROUGH cloud_store (verified
against the stub) — and the close path applies the local prompts production
flip after the cloud acks.
"""
import json
import os
import sqlite3
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cloud_store
import promotion_store


# ---------------------------------------------------------------------------
# stub Worker — records every request; each test sets the next response.

class _StubState:
    def __init__(self):
        self.requests = []          # list of {method, path, body, auth}
        self.status = 200
        self.body = {}              # dict/list -> JSON, str -> raw bytes


class _StubHandler(BaseHTTPRequestHandler):
    state = None  # set per-server

    def log_message(self, *a):      # silence
        pass

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        self.state.requests.append({
            "method": self.command,
            "path": self.path,
            "body": json.loads(raw) if raw else None,
            "auth": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "user_agent": self.headers.get("User-Agent"),
        })
        payload = self.state.body
        out = (payload if isinstance(payload, str) else json.dumps(payload)).encode()
        self.send_response(self.state.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    do_GET = _handle
    do_POST = _handle


class CloudStoreCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.state = _StubState()
        handler = type("H", (_StubHandler,), {"state": self.state})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(
            target=lambda: self.httpd.serve_forever(poll_interval=0.02), daemon=True)
        self.thread.start()
        host, port = self.httpd.server_address
        self.base = f"http://{host}:{port}"
        self._env = {}
        self._set_env("STUDIO_CLOUD_BASE_URL", self.base)
        self._set_env("STUDIO_CLOUD_TOKEN", "sekret")

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        for k, v in self._env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _set_env(self, key, value):
        self._env.setdefault(key, os.environ.get(key))
        os.environ[key] = value

    def _respond(self, body, status=200):
        self.state.body = body
        self.state.status = status

    def _last(self):
        return self.state.requests[-1]


# ---------------------------------------------------------------------------
# method + path + body + bearer

class TestRouting(CloudStoreCase):
    def test_get_promotion(self):
        promo = {"id": 7, "state": "open", "objections": [], "evidence": None}
        self._respond(promo)
        out = cloud_store.get_promotion(None, 7)
        self.assertEqual(out, promo)
        r = self._last()
        self.assertEqual((r["method"], r["path"]), ("GET", "/api/promotions/7"))
        self.assertIsNone(r["body"])
        self.assertEqual(r["auth"], "Bearer sekret")

    def test_list_promotions_returns_list_shape(self):
        promos = [{"id": 2}, {"id": 1}]
        self._respond(promos)
        out = cloud_store.list_promotions(None)
        self.assertEqual(out, promos)
        r = self._last()
        self.assertEqual((r["method"], r["path"]), ("GET", "/api/promotions"))

    def test_open_promotion_body(self):
        self._respond({"id": 9, "state": "open"})
        cloud_store.open_promotion(
            None, "greeter", "v3", window_hours=12.0,
            evidence={"source_file": "e.json", "content_hash": "h"},
            deliberation_slug="delib-1")
        r = self._last()
        self.assertEqual((r["method"], r["path"]), ("POST", "/api/promotions"))
        self.assertEqual(r["body"], {
            "prompt_id": "greeter", "version": "v3", "window_hours": 12.0,
            "evidence": {"source_file": "e.json", "content_hash": "h"},
            "deliberation_slug": "delib-1", "opened_by": "operator"})
        self.assertEqual(r["content_type"], "application/json")

    def test_add_objection_operator_channel(self):
        self._respond({"id": 1, "promotion_id": 5, "body": "no"})
        cloud_store.add_objection(None, 5, "no")
        r = self._last()
        self.assertEqual((r["method"], r["path"]),
                         ("POST", "/api/promotions/5/objections"))
        self.assertEqual(r["body"], {"body": "no"})

    def test_resolve_objection_path_and_body(self):
        self._respond({"id": 5, "state": "open"})
        cloud_store.resolve_objection(None, 5, 3, "responded", "here is why")
        r = self._last()
        self.assertEqual((r["method"], r["path"]),
                         ("POST", "/api/promotions/5/objections/3/resolve"))
        self.assertEqual(r["body"], {"resolution": "responded", "body": "here is why"})

    def test_close_promotion(self):
        self._respond({"id": 5, "state": "closed"})
        cloud_store.close_promotion(None, 5)
        r = self._last()
        self.assertEqual((r["method"], r["path"]),
                         ("POST", "/api/promotions/5/close"))
        self.assertIsNone(r["body"])

    def test_waive_promotion_body(self):
        self._respond({"id": 5, "state": "waived"})
        cloud_store.waive_promotion(None, 5, "urgent hotfix")
        r = self._last()
        self.assertEqual((r["method"], r["path"]),
                         ("POST", "/api/promotions/5/waive"))
        self.assertEqual(r["body"], {"reason": "urgent hotfix"})

    def test_abort_promotion(self):
        self._respond({"id": 5, "state": "aborted"})
        cloud_store.abort_promotion(None, 5)
        r = self._last()
        self.assertEqual((r["method"], r["path"]),
                         ("POST", "/api/promotions/5/abort"))

    def test_mark_seal_result_success(self):
        self._respond({"id": 5, "sealed": 1})
        cloud_store.mark_seal_result(None, 5, slug="ship-beta", citation_hash="sha256:h")
        r = self._last()
        self.assertEqual((r["method"], r["path"]),
                         ("POST", "/api/promotions/5/seal-result"))
        self.assertEqual(r["body"], {"slug": "ship-beta", "citation_hash": "sha256:h"})

    def test_mark_seal_result_error(self):
        self._respond({"id": 5, "sealed": 0})
        cloud_store.mark_seal_result(None, 5, error="hub down")
        self.assertEqual(self._last()["body"], {"error": "hub down"})

    def test_metrics_window_param(self):
        self._respond({"terminal_total": 0})
        cloud_store.metrics(None, 30)
        self.assertEqual(self._last()["path"], "/api/promotions/metrics?window=30")

    def test_metrics_all_time_no_param(self):
        self._respond({"terminal_total": 0})
        cloud_store.metrics(None)
        self.assertEqual(self._last()["path"], "/api/promotions/metrics")

    def test_mint_token_body_without_deliberation(self):
        self._respond({"token": "raw", "token_id": 1, "url": self.base + "/object/raw"})
        out = cloud_store.mint_token(None, 5, invitee_label="Reviewer", use_limit=2)
        r = self._last()
        self.assertEqual((r["method"], r["path"]),
                         ("POST", "/api/promotions/5/tokens"))
        self.assertEqual(r["body"], {"invitee_label": "Reviewer", "use_limit": 2})
        # response passes through (already carries the absolute url)
        self.assertEqual(out["url"], self.base + "/object/raw")

    def test_mint_token_explicit_null_deliberation_included(self):
        self._respond({"token": "raw", "token_id": 1})
        cloud_store.mint_token(None, 5, deliberation_slug=None)
        self.assertIn("deliberation_slug", self._last()["body"])
        self.assertIsNone(self._last()["body"]["deliberation_slug"])

    def test_mint_token_unset_deliberation_omitted(self):
        self._respond({"token": "raw", "token_id": 1})
        cloud_store.mint_token(None, 5)  # deliberation_slug defaults to _UNSET
        self.assertNotIn("deliberation_slug", self._last()["body"])

    def test_revoke_token_path(self):
        self._respond({"revoked": True, "token_id": 4, "promotion_id": 5})
        cloud_store.revoke_token(None, 5, 4)
        self.assertEqual(self._last()["path"], "/api/promotions/5/tokens/4/revoke")

    def test_backfill_sealed_records_uses_promotion_id(self):
        self._respond({"backfilled": 1, "promotion_id": 5})
        recs = [{"event_type": "ObjectionRaised", "record_hash": "sha256:x"}]
        cloud_store.backfill_sealed_records(None, {"id": 5}, recs, slug="ship")
        r = self._last()
        self.assertEqual((r["method"], r["path"]),
                         ("POST", "/api/promotions/5/sealed-records"))
        self.assertEqual(r["body"], {"records": recs, "slug": "ship"})

    def test_refusal_summary_window(self):
        self._respond({"total": 0, "counts": {}, "recent": []})
        cloud_store.refusal_summary(None, 7)
        self.assertEqual(self._last()["path"], "/api/object-refusals?window=7")

    def test_admin_import_no_conn(self):
        self._respond({"imported": {"promotions": 2}})
        payload = {"promotions": [{"id": 1}, {"id": 2}]}
        out = cloud_store.admin_import(payload)
        r = self._last()
        self.assertEqual((r["method"], r["path"]), ("POST", "/api/admin/import"))
        self.assertEqual(r["body"], payload)
        self.assertEqual(out, {"imported": {"promotions": 2}})

    def test_no_bearer_header_when_token_unset(self):
        os.environ.pop("STUDIO_CLOUD_TOKEN", None)
        self._respond([])
        cloud_store.list_promotions(None)
        self.assertIsNone(self._last()["auth"])

    def test_sends_custom_user_agent(self):
        # Cloudflare's edge 403s the default Python-urllib UA, so every
        # operator->Worker request must send a custom User-Agent.
        self._respond([])
        cloud_store.list_promotions(None)
        self.assertEqual(self._last()["user_agent"], cloud_store.USER_AGENT)


# ---------------------------------------------------------------------------
# error mapping

class TestErrorMapping(CloudStoreCase):
    def test_non_2xx_becomes_promotion_error_with_status(self):
        self._respond({"error": "promotion not found"}, status=404)
        with self.assertRaises(promotion_store.PromotionError) as ctx:
            cloud_store.get_promotion(None, 99)
        self.assertEqual(ctx.exception.message, "promotion not found")
        self.assertEqual(ctx.exception.status, 404)

    def test_409_conflict_body(self):
        self._respond({"error": "promotion 3 already open for greeter@v1"}, status=409)
        with self.assertRaises(promotion_store.PromotionError) as ctx:
            cloud_store.open_promotion(None, "greeter", "v1")
        self.assertEqual(ctx.exception.status, 409)
        self.assertIn("already open", ctx.exception.message)

    def test_error_with_code_field_still_maps_message(self):
        self._respond({"error": "Request body too large", "code": "x"}, status=413)
        with self.assertRaises(promotion_store.PromotionError) as ctx:
            cloud_store.mint_token(None, 5)
        self.assertEqual(ctx.exception.message, "Request body too large")
        self.assertEqual(ctx.exception.status, 413)

    def test_non_json_error_body_falls_back(self):
        self._respond("<html>boom</html>", status=500)
        with self.assertRaises(promotion_store.PromotionError) as ctx:
            cloud_store.list_promotions(None)
        self.assertEqual(ctx.exception.status, 500)
        self.assertIn("boom", ctx.exception.message)

    def test_network_failure_becomes_502(self):
        # point at a closed port so the connection is refused
        os.environ["STUDIO_CLOUD_BASE_URL"] = "http://127.0.0.1:9"
        with self.assertRaises(promotion_store.PromotionError) as ctx:
            cloud_store.list_promotions(None)
        self.assertEqual(ctx.exception.status, 502)
        self.assertIn("unreachable", ctx.exception.message)

    def test_unconfigured_base_fails_loud(self):
        os.environ.pop("STUDIO_CLOUD_BASE_URL", None)
        with self.assertRaises(promotion_store.PromotionError) as ctx:
            cloud_store.list_promotions(None)
        self.assertEqual(ctx.exception.status, 500)
        self.assertIn("STUDIO_CLOUD_BASE_URL", ctx.exception.message)


# ---------------------------------------------------------------------------
# server.py cloud-mode switch — promote / mint / resolve / close route through
# cloud_store, and close applies the local prompts flip after the cloud acks.

class TestServerCloudSwitch(CloudStoreCase):
    """Reload server with STUDIO_CLOUD_BASE_URL set so its module-level
    _CLOUD/_pstore/_ops seam points at cloud_store, then drive handlers against
    a mock request object + a local prompts DB."""

    def setUp(self):
        super().setUp()
        import importlib
        import tempfile
        import server as _server
        self.server = importlib.reload(_server)
        # local laptop DB: prompts table only (the FCP state is remote now).
        # File-backed so the handler can open/close its own connection (it
        # closes conn in a finally) and the test can re-open to verify the flip.
        fd, self.dbpath = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        seed = self._db()
        seed.execute(
            "CREATE TABLE prompts (id TEXT, version TEXT, status TEXT, "
            "eval_status TEXT, owner TEXT, updated_at TEXT, "
            "PRIMARY KEY (id, version))")
        seed.execute(
            "INSERT INTO prompts (id, version, status) VALUES ('greeter','v1','staging')")
        seed.commit()
        seed.close()

    def _db(self):
        conn = sqlite3.connect(self.dbpath)
        conn.row_factory = sqlite3.Row
        return conn

    def tearDown(self):
        os.unlink(self.dbpath)
        # restore the local-path seam for the rest of the suite
        os.environ.pop("STUDIO_CLOUD_BASE_URL", None)
        os.environ.pop("STUDIO_CLOUD_TOKEN", None)
        import importlib
        import server as _server
        importlib.reload(_server)
        super().tearDown()

    def _handler(self):
        """A server handler instance wired to send_json capture + our conn,
        WITHOUT running BaseHTTPRequestHandler.__init__ (no socket)."""
        h = self.server.PromptStudioHandler.__new__(self.server.PromptStudioHandler)
        h.sent = []
        h.send_json = lambda data, status=200: h.sent.append((data, status))
        h.get_db = lambda: self._db()
        h.read_json_body = lambda: h._body
        h.path = "/"
        return h

    def test_cloud_mode_selected(self):
        self.assertTrue(self.server._CLOUD)
        self.assertIs(self.server._pstore, self.server.cloud_store)
        self.assertIs(self.server._ops, self.server.cloud_store)

    def test_promote_routes_through_cloud_with_precheck(self):
        self._respond({"id": 1, "state": "open", "prompt_id": "greeter",
                       "version": "v1"})
        h = self._handler()
        h._body = {"evidence": None, "window_hours": 24}
        h.handle_post_promote("greeter", "v1")
        self.assertEqual(self._last()["path"], "/api/promotions")
        self.assertEqual(h.sent[-1][1], 200)

    def test_promote_precheck_unknown_prompt_404_before_cloud(self):
        h = self._handler()
        h._body = {"evidence": None}
        h.handle_post_promote("nope", "v9")
        self.assertEqual(h.sent[-1][1], 404)
        self.assertEqual(self.state.requests, [])  # never hit the cloud

    def test_promote_precheck_already_production_409(self):
        db = self._db()
        db.execute("UPDATE prompts SET status='production' "
                   "WHERE id='greeter' AND version='v1'")
        db.commit()
        db.close()
        h = self._handler()
        h._body = {"evidence": None}
        h.handle_post_promote("greeter", "v1")
        self.assertEqual(h.sent[-1][1], 409)
        self.assertEqual(self.state.requests, [])

    def test_mint_passthrough_response(self):
        self._respond({"token": "raw", "token_id": 1,
                       "url": "https://obj.example/object/raw",
                       "deliberation_url": "https://hub.example/t/d/view"})
        h = self._handler()
        h._body = {"use_limit": 1}
        h.handle_token_mint("5")
        sent = h.sent[-1][0]
        self.assertEqual(sent["url"], "https://obj.example/object/raw")
        self.assertEqual(sent["deliberation_url"], "https://hub.example/t/d/view")
        self.assertEqual(self._last()["path"], "/api/promotions/5/tokens")

    def test_resolve_routes_through_cloud(self):
        self._respond({"id": 5, "state": "open", "objections": []})
        h = self._handler()
        h._body = {"resolution": "responded", "body": "addressed"}
        h.handle_objection_resolve("5", "2")
        self.assertEqual(self._last()["path"],
                         "/api/promotions/5/objections/2/resolve")

    def test_get_promotions_renders_cloud_error_not_uncaught(self):
        # a cloud non-2xx (here 502) must reach the client as a clean JSON
        # error with its status, not bubble as an uncaught PromotionError.
        self._respond({"error": "cloud unreachable"}, status=502)
        h = self._handler()
        h.handle_get_promotions()
        self.assertEqual(h.sent[-1], ({"error": "cloud unreachable"}, 502))

    def test_get_metrics_renders_cloud_error_not_uncaught(self):
        self._respond({"error": "cloud unreachable"}, status=502)
        h = self._handler()
        h.path = "/api/promotions/metrics"
        h.handle_get_promotion_metrics()
        self.assertEqual(h.sent[-1], ({"error": "cloud unreachable"}, 502))

    def test_get_object_refusals_renders_cloud_error_not_uncaught(self):
        self._respond({"error": "cloud unreachable"}, status=502)
        h = self._handler()
        h.path = "/api/object-refusals"
        h.operator_authorized = lambda: True
        h.handle_get_object_refusals()
        self.assertEqual(h.sent[-1], ({"error": "cloud unreachable"}, 502))

    def test_close_routes_through_cloud_then_flips_local_prompt(self):
        # cloud acks the close; the handler then flips the LOCAL prompt to
        # production (the DO cannot touch the laptop prompts table).
        self._respond({"id": 1, "state": "closed", "prompt_id": "greeter",
                       "version": "v1", "evidence": None, "objections": [],
                       "sealed": 0})
        h = self._handler()
        h._body = {}
        # neutralize the seal (subprocess/hub) — not under test here
        h._seal_promotion = lambda conn, p, outcome: p
        h.handle_promotion_action("1", "close")
        self.assertEqual(self._last()["path"], "/api/promotions/1/close")
        verify = self._db()
        status = verify.execute(
            "SELECT status FROM prompts WHERE id='greeter' AND version='v1'"
        ).fetchone()["status"]
        verify.close()
        self.assertEqual(status, "production")


if __name__ == "__main__":
    unittest.main()
