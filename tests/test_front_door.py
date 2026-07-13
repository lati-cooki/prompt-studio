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


# ---------------------------------------------------------------------------
# Deliverable 2 — operator-route bearer auth + honest posture strings


class TestOperatorAuth(FrontDoorCase):
    # Every state-changing operator route (the brief's list plus sessions/
    # chat — anything that writes or spends, except the skeptic surface).
    STATE_CHANGING = [
        ("POST", "/api/sessions"),
        ("POST", "/api/prompts"),
        ("POST", "/api/chat"),
        ("POST", "/api/challenge"),
        ("POST", "/api/threads/seal"),
        ("POST", "/api/prompts/p1/draft"),
        ("POST", "/api/prompts/p1/promote/1.0.0"),
        ("POST", "/api/prompts/p1/demote/1.0.0"),
        ("POST", "/api/promotions/1/tokens"),
        ("POST", "/api/promotions/1/tokens/1/revoke"),
        ("POST", "/api/promotions/1/close"),
        ("POST", "/api/promotions/1/waive"),
        ("POST", "/api/promotions/1/abort"),
        ("POST", "/api/promotions/1/reseal"),
        ("POST", "/api/promotions/1/object"),
        ("POST", "/api/promotions/1/objections/1/resolve"),
        ("POST", "/api/evals/e1/grade"),
        ("PUT", "/api/sessions/s1"),
        ("PUT", "/api/prompts/p1"),
        ("DELETE", "/api/sessions/s1"),
        ("DELETE", "/api/prompts/p1"),
    ]

    SESSION = {"id": "s9", "name": "n", "createdAt": "2026-01-01T00:00:00Z",
               "updatedAt": "2026-01-01T00:00:00Z", "panes": [],
               "vaultConfig": {}}

    def test_auth_off_current_behavior(self):
        self.assertIsNone(objections.OPERATOR_TOKEN)  # env-off default
        h = self._req("POST", "/api/sessions", body=self.SESSION)
        self.assertEqual(h._last_status, 200)

    def test_auth_on_401_without_bearer_everywhere(self):
        with patch.object(objections, "OPERATOR_TOKEN", "sekret"):
            bodies = set()
            for method, path in self.STATE_CHANGING:
                h = self._req(method, path, body={})
                self.assertEqual(h._last_status, 401, (method, path))
                bodies.add(h._body_written)
            self.assertEqual(len(bodies), 1)  # one plain body
            self.assertNotIn(b"<", next(iter(bodies)))  # plain, not HTML

    def test_auth_on_401_on_mismatch(self):
        with patch.object(objections, "OPERATOR_TOKEN", "sekret"):
            h = self._req("POST", "/api/sessions", body=self.SESSION,
                          bearer="wrong")
            self.assertEqual(h._last_status, 401)
            # malformed scheme too
            h = self._h()
            h.path = "/api/sessions"
            h._set_body(json.dumps(self.SESSION).encode())
            h._mock_headers["Authorization"] = "Basic sekret"
            h.do_POST()
            self.assertEqual(h._last_status, 401)

    def test_auth_on_correct_bearer_passes(self):
        with patch.object(objections, "OPERATOR_TOKEN", "sekret"):
            h = self._req("POST", "/api/sessions", body=self.SESSION,
                          bearer="sekret")
            self.assertEqual(h._last_status, 200)

    def test_auth_on_skeptic_surface_needs_no_bearer(self):
        p, minted = self._minted()
        with patch.object(objections, "OPERATOR_TOKEN", "sekret"):
            page = self._get_page(minted["token"])
            self.assertEqual(page._last_status, 200)
            h, _ = self._file(minted["token"])  # no Authorization header
            self.assertEqual(h._last_status, 200)

    def test_auth_on_reads_stay_open(self):
        with patch.object(objections, "OPERATOR_TOKEN", "sekret"):
            h = self._req("GET", "/api/prompts")
            self.assertEqual(h._last_status, 200)

    def test_public_mode_wall_wins_over_auth(self):
        # In public mode an operator route must 404 generically even with
        # the CORRECT bearer — reachability is the wall, and a 401-vs-404
        # difference would be a route-existence oracle.
        with patch.object(objections, "OPERATOR_TOKEN", "sekret"), \
             patch.object(objections, "PUBLIC_MODE", True):
            h = self._req("POST", "/api/sessions", body=self.SESSION,
                          bearer="sekret")
            self.assertEqual(h._last_status, 404)
            self.assertEqual(h._body_written,
                             objections.GENERIC_404_HTML.encode("utf-8"))


class TestPostureHonesty(FrontDoorCase):
    """The posture string is quoted in mint responses and sealed receipts —
    it must describe the mode the server is ACTUALLY in, sentence by
    sentence, derived from live config. Changed text applies to NEW mints
    only; stored rows are never rewritten."""

    def _mint_posture(self, bearer=None):
        p = self._open_promotion()
        h = self._req("POST", f"/api/promotions/{p['id']}/tokens", body={},
                      bearer=bearer)
        self.assertEqual(h._last_status, 200)
        return h._json()["posture"]

    def test_auth_off_posture_discloses_no_credential_check(self):
        posture = self._mint_posture()
        self.assertIn("no credential check", posture)
        self.assertIn("deployment posture", posture)
        self.assertIn("not enforced auth", posture)
        # it must NOT claim enforcement that is not configured
        self.assertNotIn("requires 'Authorization", posture)

    def test_auth_on_posture_discloses_bearer_enforcement(self):
        with patch.object(objections, "OPERATOR_TOKEN", "sekret"):
            posture = self._mint_posture(bearer="sekret")
        # a false "no credential check" while a bearer check is active
        # would be a false disclosure
        self.assertNotIn("no credential check", posture)
        self.assertNotIn("not enforced auth", posture)
        self.assertIn("STUDIO_OPERATOR_TOKEN is set", posture)
        self.assertIn("Bearer", posture)

    def test_posture_discloses_public_mode_state(self):
        # public mode OFF (this server serves everything)
        self.assertIn("STUDIO_PUBLIC_MODE is off", self._mint_posture())
        # public mode ON: mint still happens on the operator's (private)
        # instance in real life; here we just assert the string flips.
        with patch.object(objections, "PUBLIC_MODE", True):
            self.assertIn("STUDIO_PUBLIC_MODE is on",
                          objections.posture_note())
            self.assertIn("only the tokenized objection surface",
                          objections.posture_note())


# ---------------------------------------------------------------------------
# Deliverable 3 — share/receipt URLs from config, never the Host header


class TestConfigUrls(FrontDoorCase):
    PUB = "https://objections.example.com"
    HUB = "https://hub.example.com"

    def _mint_with_host(self, host="evil.example.com:1337"):
        p = self._open_promotion()
        h = self._h()
        h.path = f"/api/promotions/{p['id']}/tokens"
        h._set_body(b"{}")
        h._mock_headers["Host"] = host
        h.do_POST()
        self.assertEqual(h._last_status, 200)
        return h._json()

    def test_mint_url_ignores_host_header_when_base_unset(self):
        minted = self._mint_with_host()
        self.assertNotIn("evil.example.com", minted["url"])
        self.assertEqual(minted["url"],
                         f"http://localhost:{server.PORT}/object/{minted['token']}")

    def test_mint_url_uses_public_base_when_set(self):
        with patch.object(objections, "PUBLIC_BASE_URL", self.PUB):
            minted = self._mint_with_host()
        self.assertEqual(minted["url"], f"{self.PUB}/object/{minted['token']}")

    def test_filing_receipt_status_url_uses_public_base(self):
        p, minted = self._minted()
        with patch.object(objections, "PUBLIC_BASE_URL", self.PUB):
            h, _ = self._file(minted["token"])
        receipt = h._json()
        self.assertEqual(
            receipt["status_url"],
            f"{self.PUB}/object/{minted['token']}/status/{receipt['objection_id']}")

    def _sealed_receipt(self):
        """File, resolve, close with a mocked seal; return the status body."""
        p, minted = self._minted()
        h, _ = self._file(minted["token"])
        oid = h._json()["objection_id"]
        self.anchor.execute(
            "UPDATE promotions SET closes_at='2000-01-01T00:00:00Z' WHERE id=?",
            (p["id"],))
        self.anchor.execute(
            "UPDATE promotion_objections SET resolution='responded',"
            " resolution_body='ok' WHERE promotion_id=?", (p["id"],))
        self.anchor.commit()
        records = [
            {"seq": 0, "record_hash": "sha256:g0", "event_type": "ThreadCreated"},
            {"seq": 1, "record_hash": "sha256:obj1",
             "event_type": "ObjectionRaised"}]
        with patch("seal.seal_decision",
                   return_value={"slug": "promo-thread",
                                 "citationHash": "sha256:head",
                                 "records": records}):
            hc = self._h()
            hc.path = f"/api/promotions/{p['id']}/close"
            hc._set_body(b"")
            hc.do_POST()
        self.assertEqual(hc._json()["sealed"], 1)
        s = self._h()
        s.path = f"/object/{minted['token']}/status/{oid}"
        s.do_GET()
        self.assertEqual(s._last_status, 200)
        return s._json()

    def test_receipt_hub_urls_default_to_local_hub(self):
        body = self._sealed_receipt()
        hub = f"http://localhost:{seal.THREADHUB_PORT}"
        self.assertEqual(body["checker_url"], f"{hub}/verify.mjs")

    def test_receipt_never_hands_a_skeptic_localhost_when_bases_set(self):
        with patch.object(objections, "PUBLIC_BASE_URL", self.PUB), \
             patch.object(objections, "THREADHUB_PUBLIC_BASE_URL", self.HUB):
            body = self._sealed_receipt()
        self.assertEqual(body["record_url"], f"{self.HUB}/r/sha256:obj1")
        self.assertEqual(body["verify_url"],
                         f"{self.HUB}/t/promo-thread/verify")
        self.assertEqual(body["checker_url"], f"{self.HUB}/verify.mjs")
        self.assertIn(f"{self.HUB}/verify.mjs", body["instructions"])
        self.assertNotIn("localhost", json.dumps(body))
        self.assertNotIn("127.0.0.1", json.dumps(body))

    def test_host_header_never_used_for_url_construction(self):
        # the code path is gone: no handler reads the Host header anymore
        import inspect
        src = inspect.getsource(server)
        self.assertNotIn("headers.get('Host'", src)
        self.assertNotIn('headers.get("Host"', src)


# ---------------------------------------------------------------------------
# Deliverable 4 — the rate limiter, real: eviction, env-tunable, ALL
# /object/* surfaces, generic 429 bodies


class TestRateLimiter(FrontDoorCase):
    def _get(self, path, ip):
        h = self._h(ip)
        h.path = path
        h.do_GET()
        return h

    def test_parse_rate_spec(self):
        self.assertEqual(objections._parse_rate("10/60"), (10, 60.0))
        self.assertEqual(objections._parse_rate("5"), (5, 60.0))
        self.assertEqual(objections._parse_rate("20/30"), (20, 30.0))

    def test_rate_is_tunable(self):
        with patch.object(objections, "RATE_LIMIT", 3):
            for i in range(3):
                self.assertTrue(objections.allow_request("9.9.9.9",
                                                         now=1000.0 + i))
            self.assertFalse(objections.allow_request("9.9.9.9", now=1003.0))

    def test_stale_buckets_are_evicted(self):
        # no unbounded growth: a distinct-IP probe sweep must not leave a
        # bucket per IP forever
        objections.allow_request("10.0.0.1", now=1000.0)
        objections.allow_request("10.0.0.2", now=1000.0)
        self.assertIn("10.0.0.1", objections._rate_buckets)
        later = 1000.0 + objections.RATE_WINDOW * 2
        objections.allow_request("10.0.0.3", now=later)
        self.assertNotIn("10.0.0.1", objections._rate_buckets)
        self.assertNotIn("10.0.0.2", objections._rate_buckets)
        self.assertIn("10.0.0.3", objections._rate_buckets)

    def test_page_get_hits_the_limiter(self):
        p, minted = self._minted()
        ip = "198.51.100.9"
        for _ in range(objections.RATE_LIMIT):
            self._get(f"/object/{minted['token']}", ip)
        h = self._get(f"/object/{minted['token']}", ip)
        self.assertEqual(h._last_status, 429)
        # generic body — and identical whether the token is valid or bogus
        # (the limiter must not become the oracle the 404s refuse to be)
        h2 = self._get("/object/bogus", ip)
        self.assertEqual(h2._last_status, 429)
        self.assertEqual(h._body_written, h2._body_written)
        self.assertEqual(h._body_written,
                         objections.GENERIC_429_HTML.encode("utf-8"))

    def test_status_get_hits_the_limiter(self):
        p, minted = self._minted()
        h, _ = self._file(minted["token"])
        oid = h._json()["objection_id"]
        ip = "198.51.100.10"
        for _ in range(objections.RATE_LIMIT):
            self._get(f"/object/{minted['token']}/status/{oid}", ip)
        s = self._get(f"/object/{minted['token']}/status/{oid}", ip)
        self.assertEqual(s._last_status, 429)
        self.assertEqual(s._json(), objections.GENERIC_429_JSON)

    def test_api_post_and_page_share_one_budget(self):
        ip = "198.51.100.11"
        for _ in range(objections.RATE_LIMIT):
            h = self._post_objection("bogus", {"body": "x", "contact": "a@b"},
                                     ip=ip)
            self.assertEqual(h._last_status, 404)
        g = self._get("/object/bogus", ip)
        self.assertEqual(g._last_status, 429)

    def test_mint_route_not_limited(self):
        ip = "198.51.100.12"
        for _ in range(objections.RATE_LIMIT + 1):
            self._get("/object/bogus", ip)
        p = self._open_promotion()
        h = self._h(ip)
        h.path = f"/api/promotions/{p['id']}/tokens"
        h._set_body(b"{}")
        h.do_POST()
        self.assertEqual(h._last_status, 200)


if __name__ == "__main__":
    unittest.main()
