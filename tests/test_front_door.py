"""Task 13 — hosting hardening: the front door, before the first send.

In-repo home for the front-door security surface (the git-ignored local
test_security.py stays local). Covers:

1. PUBLIC_MODE surface restriction (STUDIO_PUBLIC_MODE=1): ONLY the skeptic
   surface is served — GET /object/<token>, POST /api/object/<token>,
   GET /object/<token>/status/<oid>. Everything else answers the
   byte-identical generic 404 the token paths use (no route-existence
   oracle). Static assets: NONE on purpose — the objection page is fully
   self-contained (inline CSS + inline JS), so public mode serves zero
   static files and leaves no file-existence oracle.
2. Operator-route bearer auth (STUDIO_OPERATOR_TOKEN) with honest,
   config-derived posture strings — the posture text must describe the mode
   the server is ACTUALLY in.
3. Share/receipt URLs from config (STUDIO_PUBLIC_BASE_URL,
   THREADHUB_PUBLIC_BASE_URL) — never from the Host header, and never a
   localhost URL in a skeptic's receipt when public bases are configured.
4. The real rate limiter: bucket eviction, env-tunable rate/window
   (STUDIO_OBJECT_RATE), applied to ALL /object/* and /api/object/*
   surfaces, generic 429 bodies.
5. Timing normalization keeps the oracle set-tests byte-identical
   (including under the limiter and the refusal audit).
6. The refusal audit (object_refusals): insert-only witnesses per refusal
   branch, prober-visible surface unchanged, operator-auth'd summary route.
7. allow_reuse_address on the server class (TIME_WAIT hygiene).
"""
import json
import os
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import objections
import seal
import server
from test_objections_api import TokenPathTestCase


class FrontDoorCase(TokenPathTestCase):
    """TokenPathTestCase (shared in-memory DB, operator writer provisioned,
    rate buckets cleared) + a generic request helper."""

    maxDiff = None

    def _req(self, method, path, body=None, bearer=None, ip="203.0.113.5"):
        h = self._h(ip)
        h.path = path
        h._set_body(b"" if body is None else json.dumps(body).encode())
        if bearer is not None:
            h._mock_headers["Authorization"] = f"Bearer {bearer}"
        getattr(h, f"do_{method}")()
        return h


# ---------------------------------------------------------------------------
# Deliverable 1 — PUBLIC_MODE surface restriction


class TestPublicMode(FrontDoorCase):
    # Route-by-route sweep material: every non-skeptic route the server
    # knows, plus paths it does NOT know — in public mode they must be
    # indistinguishable (no route-existence oracle).
    NON_SKEPTIC = {
        "GET": [
            "/", "/sandbox", "/sandbox/", "/registry", "/threads",
            "/js/app.js", "/registry-asset/INDEX.json",
            "/api/sessions", "/api/prompts", "/api/registry",
            "/api/promotions", "/api/promotions/1",
            "/api/promotions/metrics", "/api/threads", "/api/threads/x",
            "/api/threads/x/verify", "/api/challenge/demo",
            "/api/challenge/j1", "/api/object-refusals",
            "/object", "/favicon.ico", "/server.py", "/schema.sql",
            "/no-such-route",
        ],
        "POST": [
            "/api/sessions", "/api/prompts", "/api/chat", "/api/challenge",
            "/api/threads/seal", "/api/prompts/p1/draft",
            "/api/prompts/p1/1.0.0/validate",
            "/api/prompts/p1/promote/1.0.0", "/api/prompts/p1/demote/1.0.0",
            "/api/promotions/1/tokens", "/api/promotions/1/close",
            "/api/promotions/1/waive", "/api/promotions/1/abort",
            "/api/promotions/1/reseal", "/api/promotions/1/object",
            "/api/promotions/1/tokens/1/revoke",
            "/api/promotions/1/objections/1/resolve",
            "/api/evals/e1/grade", "/api/object", "/api/objectx",
            "/no-such-route",
        ],
        "PUT": ["/api/sessions/s1", "/api/prompts/p1", "/no-such-route"],
        "DELETE": ["/api/sessions/s1", "/api/prompts/p1", "/no-such-route"],
    }

    def test_default_off_studio_routes_served(self):
        self.assertFalse(objections.PUBLIC_MODE)  # env-off default
        h = self._req("GET", "/api/prompts")
        self.assertEqual(h._last_status, 200)

    def test_public_mode_404s_every_non_skeptic_route_identically(self):
        generic = objections.GENERIC_404_HTML.encode("utf-8")
        with patch.object(objections, "PUBLIC_MODE", True):
            bodies = set()
            for method, paths in self.NON_SKEPTIC.items():
                for path in paths:
                    h = self._req(method, path, body={})
                    self.assertEqual(h._last_status, 404, (method, path))
                    bodies.add(h._body_written)
        self.assertEqual(bodies, {generic})  # byte-identical, the ONE body

    def test_public_mode_404s_options_too(self):
        with patch.object(objections, "PUBLIC_MODE", True):
            h = self._req("OPTIONS", "/api/prompts")
            self.assertEqual(h._last_status, 404)
            self.assertEqual(h._body_written,
                             objections.GENERIC_404_HTML.encode("utf-8"))

    def test_public_mode_serves_the_skeptic_surface(self):
        p, minted = self._minted()
        with patch.object(objections, "PUBLIC_MODE", True):
            page = self._get_page(minted["token"])
            self.assertEqual(page._last_status, 200)
            h, _ = self._file(minted["token"])
            self.assertEqual(h._last_status, 200)
            receipt = h._json()
            s = self._h()
            s.path = f"/object/{minted['token']}/status/{receipt['objection_id']}"
            s.do_GET()
            self.assertEqual(s._last_status, 200)

    def test_public_mode_token_failure_matches_the_wall(self):
        # An invalid token on the SKEPTIC surface and a non-skeptic route
        # behind the wall must be indistinguishable: same 404, same bytes.
        with patch.object(objections, "PUBLIC_MODE", True):
            invalid = self._get_page("bogus")
            walled = self._req("GET", "/api/prompts")
        self.assertEqual(invalid._last_status, 404)
        self.assertEqual(walled._last_status, 404)
        self.assertEqual(invalid._body_written, walled._body_written)


if __name__ == "__main__":
    unittest.main()
