"""Task 15 — the studio side of "the record is the interface"
(DR-2026-07-13-record-is-the-interface, rule 2).

Covers:

- publication.effective_publication: the Python mirror of the hub's pure
  function (packages/threadhub/src/publication.js) — last publication event
  wins, fail closed on malformed acts / unregistered scopes.
- POST /api/threads/<slug>/publish|unpublish: an OPERATOR-authored witnessed
  act appended to the hub thread via the existing record-append path
  (seal._th POST /t/<slug>/records). Idempotent: effective state is read
  from the hub FIRST; publishing an already-published thread appends
  nothing and says so. Refuses 409 when the operator writer is not
  provisioned (publication is an act with an actor — never the legacy
  shared studio author). Acts log to the server log with actor + slug.
- deliberation_slug association on promotions: settable at promotion open
  and overridable at token mint; the guarded migration adds the column.
- the doorstep link: the objection page and the mint response carry the
  hub viewer URL ONLY when an association exists AND the thread is
  effectively published — an unpublished association renders NOTHING
  (no dead links, no slug leakage).
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import objections
import promotion_store
import publication
import seal
import server
import writers
from test_objections_api import ObjectionsTestCase
from test_promotions_api import MockHandler

RECORD_HASH = "sha256:" + "a" * 64


def _pub_event(action="publish", overrides=None):
    """A ClisTa publication event payload shaped exactly like the hub's
    publication.test.js fixture (overrides patch the threadPublication
    object, so a mismatched action/scope can be constructed)."""
    tp = {
        "id": "tpb_fixture1",
        "object": "threadPublication",
        "threadId": "thd_1",
        "action": action,
        "scope": "public-read",
        "publishedByParticipantId": "id_troy",
        "publishedAt": "2026-07-12T00:00:00Z",
    }
    tp.update(overrides or {})
    return {
        "event_type": ("ThreadPublished" if action == "publish"
                       else "ThreadPublicationRevoked"),
        "actor_id": "id_troy",
        "timestamp": "2026-07-12T00:00:00Z",
        "payload": {"threadPublication": tp},
    }


def _env(kind, payload):
    return {"kind": kind, "thread": "thd_1", "payload": payload}


GENESIS = _env("genesis", {"title": "t"})
NOTE = _env("note", {"n": 1})


class TestEffectivePublication(unittest.TestCase):
    """The pure function — mirror of the hub's src/publication.js."""

    def test_no_publication_event_means_unpublished(self):
        self.assertFalse(publication.effective_publication([])["published"])
        self.assertFalse(
            publication.effective_publication([GENESIS, NOTE])["published"])

    def test_publish_event_publishes(self):
        state = publication.effective_publication(
            [GENESIS, _env("clista.event", _pub_event("publish"))])
        self.assertTrue(state["published"])
        self.assertEqual(state["act"]["action"], "publish")

    def test_last_publication_event_wins(self):
        state = publication.effective_publication([
            _env("clista.event", _pub_event("publish")),
            NOTE,
            _env("clista.event", _pub_event("revoke")),
        ])
        self.assertFalse(state["published"])

    def test_republish_after_revoke(self):
        state = publication.effective_publication([
            _env("clista.event", _pub_event("publish")),
            _env("clista.event", _pub_event("revoke")),
            _env("clista.event", _pub_event("publish")),
        ])
        self.assertTrue(state["published"])

    def test_fails_closed_on_scope_action_and_malformed(self):
        self.assertFalse(publication.effective_publication([
            _env("clista.event", _pub_event("publish", {"scope": "everyone"})),
        ])["published"])
        self.assertFalse(publication.effective_publication([
            _env("clista.event", _pub_event("publish", {"action": "revoke"})),
        ])["published"])
        # a malformed LAST publication event masks an earlier publish
        self.assertFalse(publication.effective_publication([
            _env("clista.event", _pub_event("publish")),
            _env("clista.event", {"event_type": "ThreadPublished",
                                  "payload": {}}),
        ])["published"])


# ---------------------------------------------------------------------------
# drift alarm — the Python mirror vs the REAL hub function, same fixture
# (review fix, Task 15). Path convention mirrors challenge.py's protocol-root
# resolution: main monorepo checkout by default, env override supreme.

HUB_PUBLICATION_JS = os.environ.get(
    "THREADHUB_PUBLICATION_JS",
    "/Users/troylatimer/Projects/clista/packages/threadhub/src/publication.js")
NODE_BIN = shutil.which("node")
DRIFT_TOOLING = bool(NODE_BIN and os.path.exists(HUB_PUBLICATION_JS))
DRIFT_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "fixtures", "publication_drift_cases.json")

# node -e runner: feed the SAME fixture cases to the hub's own
# effectivePublication and print {case_name: published} for comparison.
_NODE_DRIFT_RUNNER = """
const { effectivePublication } = require(process.argv[1]);
const fs = require('node:fs');
const fixture = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = {};
for (const c of fixture.cases) out[c.name] = effectivePublication(c.envelopes).published;
process.stdout.write(JSON.stringify(out));
"""


class TestDriftToolingPresence(unittest.TestCase):
    """Missing drift tooling must be a LOUD failure, not a silent green skip
    (tests/test_challenge.py's TestToolingPresence pattern). The drift test
    below is the only alarm that fires when the hub's publication rules
    change and the studio's mirror doesn't — drift is asymmetric in the
    worst direction (hub tightens, studio doesn't → the studio renders a
    doorstep link the hub 404s, a dead link in front of an invited
    skeptic). This suite runs on the dev machine, where node and the main
    monorepo checkout exist; if they don't, say so precisely instead of
    letting the mirror go unwatched."""

    def test_drift_tooling_available(self):
        missing = []
        if not NODE_BIN:
            missing.append("node executable on PATH")
        if not os.path.exists(HUB_PUBLICATION_JS):
            missing.append(
                f"hub publication.js at {HUB_PUBLICATION_JS} "
                "(set THREADHUB_PUBLICATION_JS)")
        self.assertFalse(
            missing,
            "publication drift tooling missing — the mirror-vs-hub drift "
            "test is SKIPPING, which this sentinel refuses to let pass "
            "silently:\n  " + "\n  ".join(missing))


@unittest.skipUnless(DRIFT_TOOLING, "node + hub publication.js required")
class TestMirrorMatchesHub(unittest.TestCase):
    """Feed the shared fixture cases to BOTH implementations and assert
    verdict equality case-by-case. The fixture's 'expected' values pin
    today's semantics; the equality assertion is the drift alarm."""

    REQUIRED_CASES = {
        "publish-only", "publish-then-revoke", "revoke-then-republish",
        "revoke-with-no-prior-publish",
        "malformed-last-act-masks-earlier-publish", "wrong-scope",
        "wrong-action-for-event-type",
        "publication-payload-on-non-clista-kind-is-ignored", "empty-thread",
    }

    def test_python_mirror_agrees_with_hub_function_on_shared_fixture(self):
        with open(DRIFT_FIXTURE) as f:
            fixture = json.load(f)
        names = {c["name"] for c in fixture["cases"]}
        # a renamed/dropped case must not make this test vacuously green
        self.assertTrue(self.REQUIRED_CASES <= names,
                        f"fixture lost cases: {self.REQUIRED_CASES - names}")
        proc = subprocess.run(
            [NODE_BIN, "-e", _NODE_DRIFT_RUNNER,
             HUB_PUBLICATION_JS, DRIFT_FIXTURE],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0,
                         f"hub-side runner failed: {proc.stderr[:500]}")
        hub_verdicts = json.loads(proc.stdout)
        for case in fixture["cases"]:
            name = case["name"]
            py = publication.effective_publication(
                case["envelopes"])["published"]
            self.assertIn(name, hub_verdicts)
            self.assertEqual(
                py, hub_verdicts[name],
                f"DRIFT on '{name}': studio mirror says {py}, hub's "
                f"effectivePublication says {hub_verdicts[name]} — update "
                "publication.effective_publication to match the hub "
                "(publication.js) and extend this fixture")
            self.assertEqual(
                py, case["expected"],
                f"semantics moved on '{name}': both implementations now say "
                f"{py} but the fixture pinned {case['expected']} — if the "
                "rule change is intended, update the fixture deliberately")


class TestIsPublishedFailClosed(unittest.TestCase):
    def test_is_published_false_on_hub_failure(self):
        with patch("publication._fetch_envelopes",
                   side_effect=publication.PublicationError(
                       "ThreadHub is not reachable", 502)):
            self.assertFalse(publication.is_published("delib-1"))

    def test_is_published_true_for_published_thread(self):
        with patch("publication._fetch_envelopes", return_value=[
                GENESIS, _env("clista.event", _pub_event("publish"))]):
            self.assertTrue(publication.is_published("delib-1"))


class TestPublishRoutes(ObjectionsTestCase):
    """POST /api/threads/<slug>/publish|unpublish through the dispatch path
    (operator writer 'id_troy' provisioned by ObjectionsTestCase.setUp)."""

    def _post(self, path):
        h = self._h()
        h.path = path
        h._set_body(b"")
        h.do_POST()
        return h

    def _publish(self, slug="demo-1", verb="publish",
                 envelopes=(GENESIS, NOTE)):
        with patch("publication._fetch_envelopes",
                   return_value=list(envelopes)), \
             patch("seal._th",
                   return_value={"record_hash": RECORD_HASH, "seq": 2}) as th:
            h = self._post(f"/api/threads/{slug}/{verb}")
        return h, th

    def test_publish_appends_operator_authored_publication_event(self):
        h, th = self._publish()
        self.assertEqual(h._last_status, 200)
        body = h._json()
        self.assertEqual(body["slug"], "demo-1")
        self.assertTrue(body["published"])
        self.assertTrue(body["changed"])
        self.assertEqual(body["seq"], 2)
        self.assertEqual(body["record_hash"], RECORD_HASH)
        th.assert_called_once()
        method, path, record = th.call_args[0]
        self.assertEqual((method, path), ("POST", "/t/demo-1/records"))
        # authored by the OPERATOR writer identity, never the studio author
        self.assertEqual(record["author"], "id_troy")
        self.assertEqual(record["kind"], "clista.event")
        event = record["payload"]
        self.assertEqual(event["event_type"], "ThreadPublished")
        self.assertEqual(event["actor_id"], "id_troy")
        tp = event["payload"]["threadPublication"]
        self.assertEqual(tp["action"], "publish")
        self.assertEqual(tp["scope"], "public-read")
        self.assertEqual(tp["publishedByParticipantId"], "id_troy")
        self.assertEqual(tp["threadId"], "thd_1")  # from the hub export
        self.assertEqual(tp["object"], "threadPublication")
        self.assertTrue(tp["id"].startswith("tpb_"))
        self.assertTrue(tp["publishedAt"])

    def test_publish_is_idempotent_appends_nothing_when_published(self):
        h, th = self._publish(envelopes=(
            GENESIS, _env("clista.event", _pub_event("publish"))))
        self.assertEqual(h._last_status, 200)
        body = h._json()
        self.assertTrue(body["published"])
        self.assertFalse(body["changed"])
        self.assertNotIn("record_hash", body)
        self.assertIn("note", body)  # says so, instead of pretending
        th.assert_not_called()

    def test_unpublish_appends_revoke_event(self):
        h, th = self._publish(verb="unpublish", envelopes=(
            GENESIS, _env("clista.event", _pub_event("publish"))))
        self.assertEqual(h._last_status, 200)
        body = h._json()
        self.assertFalse(body["published"])
        self.assertTrue(body["changed"])
        th.assert_called_once()
        event = th.call_args[0][2]["payload"]
        self.assertEqual(event["event_type"], "ThreadPublicationRevoked")
        tp = event["payload"]["threadPublication"]
        self.assertEqual(tp["action"], "revoke")
        self.assertEqual(tp["scope"], "public-read")

    def test_unpublish_is_idempotent_when_not_published(self):
        h, th = self._publish(verb="unpublish", envelopes=(GENESIS, NOTE))
        self.assertEqual(h._last_status, 200)
        self.assertFalse(h._json()["changed"])
        th.assert_not_called()

    def test_publish_refuses_409_when_operator_unprovisioned(self):
        # Publication is an act with an actor: no operator writer, no act —
        # never a silent fallback to the legacy shared studio author.
        self._drop_operator()
        h, th = self._publish()
        self.assertEqual(h._last_status, 409)
        self.assertIn("operator", h._json()["error"])
        th.assert_not_called()

    def test_publish_rejects_bad_slug(self):
        h, th = self._publish(slug="no%2Fslash")
        self.assertEqual(h._last_status, 400)
        th.assert_not_called()

    def test_publish_404_when_hub_has_no_such_thread(self):
        with patch("publication._fetch_envelopes",
                   side_effect=publication.PublicationError(
                       "thread not found on the hub", 404)), \
             patch("seal._th") as th:
            h = self._post("/api/threads/ghost/publish")
        self.assertEqual(h._last_status, 404)
        th.assert_not_called()

    def test_publish_502_when_hub_unreachable(self):
        with patch("publication._fetch_envelopes",
                   side_effect=publication.PublicationError(
                       "ThreadHub is not reachable", 502)):
            h = self._post("/api/threads/demo-1/publish")
        self.assertEqual(h._last_status, 502)

    def test_publication_acts_log_actor_and_slug(self):
        with self.assertLogs(level="INFO") as logs:
            self._publish()
            self._publish(verb="unpublish", envelopes=(
                GENESIS, _env("clista.event", _pub_event("publish"))))
        joined = "\n".join(logs.output)
        self.assertIn("publish", joined)
        self.assertIn("unpublish", joined)
        self.assertIn("demo-1", joined)
        self.assertIn("operator", joined)
        self.assertIn("id_troy", joined)

    def test_publish_requires_bearer_when_operator_token_set(self):
        with patch.object(objections, "OPERATOR_TOKEN", "sekret"):
            h, th = self._publish()
        self.assertEqual(h._last_status, 401)
        th.assert_not_called()

    def test_publish_walled_off_in_public_mode(self):
        with patch.object(objections, "PUBLIC_MODE", True):
            h, th = self._publish()
        self.assertEqual(h._last_status, 404)
        self.assertEqual(h._body_written,
                         objections.GENERIC_404_HTML.encode("utf-8"))
        th.assert_not_called()

    def test_get_publication_state(self):
        with patch("publication._fetch_envelopes", return_value=[
                GENESIS, _env("clista.event", _pub_event("publish"))]):
            h = self._h()
            h.path = "/api/threads/demo-1/publication"
            h.do_GET()
        self.assertEqual(h._last_status, 200)
        body = h._json()
        self.assertTrue(body["published"])
        self.assertEqual(body["slug"], "demo-1")


class TestDeliberationAssociation(ObjectionsTestCase):
    """deliberation_slug on promotions: open-time field, mint-time override,
    guarded migration."""

    def test_guarded_migration_adds_deliberation_slug(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("""CREATE TABLE promotions (
            id INTEGER PRIMARY KEY, prompt_id TEXT, version TEXT)""")
        conn.execute("CREATE TABLE promotion_objections (id INTEGER PRIMARY KEY)")
        server.migrate_actor_columns(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(promotions)")}
        self.assertIn("deliberation_slug", cols)
        server.migrate_actor_columns(conn)  # idempotent

    def test_schema_creates_deliberation_slug(self):
        cols = {r[1] for r in self.anchor.execute(
            "PRAGMA table_info(promotions)")}
        self.assertIn("deliberation_slug", cols)

    def test_promote_accepts_deliberation_slug(self):
        with patch("promotion_evidence.pin_evidence", return_value=None):
            h = self._h()
            h.path = "/api/prompts/p1/promote/1.0.0"
            h._set_body(json.dumps(
                {"deliberation_slug": "delib-1"}).encode())
            h.do_POST()
        self.assertEqual(h._last_status, 200)
        self.assertEqual(h._json()["deliberation_slug"], "delib-1")
        p = promotion_store.get_promotion(self.anchor, h._json()["id"])
        self.assertEqual(p["deliberation_slug"], "delib-1")

    def test_promote_rejects_unsafe_deliberation_slug(self):
        with patch("promotion_evidence.pin_evidence", return_value=None):
            h = self._h()
            h.path = "/api/prompts/p1/promote/1.0.0"
            h._set_body(json.dumps(
                {"deliberation_slug": "../etc"}).encode())
            h.do_POST()
        self.assertEqual(h._last_status, 422)
        self.assertEqual(self.anchor.execute(
            "SELECT COUNT(*) FROM promotions").fetchone()[0], 0)

    def test_promote_without_field_leaves_association_null(self):
        p = self._open_promotion()
        self.assertIsNone(p["deliberation_slug"])

    def test_mint_override_sets_association(self):
        p = self._open_promotion()
        h = self._mint(p["id"], {"deliberation_slug": "delib-2"})
        self.assertEqual(h._last_status, 200)
        self.assertEqual(h._json()["deliberation_slug"], "delib-2")
        row = self.anchor.execute(
            "SELECT deliberation_slug FROM promotions WHERE id=?",
            (p["id"],)).fetchone()
        self.assertEqual(row["deliberation_slug"], "delib-2")

    def test_mint_override_null_clears_association(self):
        p = promotion_store.open_promotion(
            self.anchor, "p1", "1.0.0", deliberation_slug="delib-1")
        h = self._mint(p["id"], {"deliberation_slug": None})
        self.assertEqual(h._last_status, 200)
        row = self.anchor.execute(
            "SELECT deliberation_slug FROM promotions WHERE id=?",
            (p["id"],)).fetchone()
        self.assertIsNone(row["deliberation_slug"])

    def test_mint_without_field_keeps_association(self):
        p = promotion_store.open_promotion(
            self.anchor, "p1", "1.0.0", deliberation_slug="delib-1")
        with patch("publication.is_published", return_value=False):
            h = self._mint(p["id"])
        self.assertEqual(h._last_status, 200)
        self.assertEqual(h._json()["deliberation_slug"], "delib-1")

    def test_mint_rejects_unsafe_deliberation_slug(self):
        p = self._open_promotion()
        h = self._mint(p["id"], {"deliberation_slug": "a/b"})
        self.assertEqual(h._last_status, 422)
        # refused BEFORE mint_token ran: no token row, no table needed
        has_table = self.anchor.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='fcp_tokens'"
        ).fetchone()[0]
        if has_table:
            self.assertEqual(self.anchor.execute(
                "SELECT COUNT(*) FROM fcp_tokens").fetchone()[0], 0)


class TestDoorstepLink(ObjectionsTestCase):
    """The viewer link renders ONLY when associated AND effectively
    published — no dead links, no slug leakage."""

    DOORSTEP = "Read the deliberation this decision cites"

    def _mint_with(self, deliberation_slug=None, published=False):
        if deliberation_slug:
            p = promotion_store.open_promotion(
                self.anchor, "p1", "1.0.0",
                deliberation_slug=deliberation_slug)
        else:
            p = self._open_promotion()
        checker = MagicMock(return_value=published)
        with patch("publication.is_published", checker):
            h = self._mint(p["id"])
        return h, checker

    def _page(self, raw, published):
        h = self._h()
        h.path = f"/object/{raw}"
        with patch("publication.is_published", return_value=published):
            h.do_GET()
        return h

    def test_mint_includes_viewer_url_when_published(self):
        h, _ = self._mint_with("delib-1", published=True)
        self.assertEqual(
            h._json()["deliberation_url"],
            f"http://localhost:{seal.THREADHUB_PORT}/t/delib-1/view")

    def test_mint_viewer_url_uses_public_hub_base_when_set(self):
        with patch.object(objections, "THREADHUB_PUBLIC_BASE_URL",
                          "https://hub.example.com"):
            h, _ = self._mint_with("delib-1", published=True)
        self.assertEqual(h._json()["deliberation_url"],
                         "https://hub.example.com/t/delib-1/view")

    def test_mint_omits_viewer_url_when_unpublished(self):
        h, _ = self._mint_with("delib-1", published=False)
        self.assertNotIn("deliberation_url", h._json())

    def test_mint_never_checks_hub_without_association(self):
        h, checker = self._mint_with(None, published=True)
        self.assertNotIn("deliberation_url", h._json())
        checker.assert_not_called()

    def test_object_page_renders_doorstep_link_when_published(self):
        mint, _ = self._mint_with("delib-1", published=True)
        h = self._page(mint._json()["token"], published=True)
        self.assertEqual(h._last_status, 200)
        page = h._body_written.decode("utf-8")
        self.assertIn(self.DOORSTEP, page)
        self.assertIn("/t/delib-1/view", page)

    def test_object_page_renders_nothing_when_unpublished(self):
        # An unpublished association renders NOTHING: no dead link, and the
        # slug itself never reaches the page bytes.
        mint, _ = self._mint_with("delib-1", published=False)
        h = self._page(mint._json()["token"], published=False)
        self.assertEqual(h._last_status, 200)
        page = h._body_written.decode("utf-8")
        self.assertNotIn(self.DOORSTEP, page)
        self.assertNotIn("delib-1", page)

    def test_object_page_unassociated_promotion_has_no_link(self):
        mint, _ = self._mint_with(None)
        h = self._h()
        h.path = f"/object/{mint._json()['token']}"
        with patch("publication.is_published",
                   MagicMock(return_value=True)) as checker:
            h.do_GET()
        self.assertEqual(h._last_status, 200)
        self.assertNotIn(self.DOORSTEP, h._body_written.decode("utf-8"))
        checker.assert_not_called()

    def test_deliberation_link_fails_closed_when_hub_down(self):
        promotion = {"deliberation_slug": "delib-1"}
        with patch("publication._fetch_envelopes",
                   side_effect=OSError("connection refused")):
            self.assertIsNone(objections.deliberation_link(promotion))

    def test_hub_down_associated_page_is_byte_identical_to_unassociated(self):
        # The end-to-end pin of the named-check property: during a hub
        # outage an ASSOCIATED promotion's page must serve the exact bytes
        # an UNASSOCIATED promotion serves (timing may differ — disclosed
        # in publication._fetch_envelopes — but bytes never do).
        p = promotion_store.open_promotion(
            self.anchor, "p1", "1.0.0", deliberation_slug="delib-1")
        with patch("publication.is_published", return_value=False):
            mint = self._mint(p["id"])
        raw = mint._json()["token"]

        h1 = self._h()
        h1.path = f"/object/{raw}"
        with patch("publication._fetch_envelopes",
                   side_effect=OSError("hub down")):
            h1.do_GET()
        self.assertEqual(h1._last_status, 200)

        self.anchor.execute(
            "UPDATE promotions SET deliberation_slug=NULL WHERE id=?",
            (p["id"],))
        self.anchor.commit()
        h2 = self._h()
        h2.path = f"/object/{raw}"
        with patch("publication._fetch_envelopes", MagicMock()) as fetch:
            h2.do_GET()
        self.assertEqual(h2._last_status, 200)
        fetch.assert_not_called()  # unassociated never even asks the hub
        self.assertEqual(h1._body_written, h2._body_written)


if __name__ == "__main__":
    unittest.main()
