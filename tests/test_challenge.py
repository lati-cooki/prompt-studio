"""Tests for challenge.py — the Studio Challenge Run (Phase 5 Wave 3 / Slice 7).

Layers covered:
  * canonical JSON + content_hash — pinned to the monorepo's integrity.js by a
    literal fixture vector (computed once with that file; drift breaks it here)
  * ClisTa event construction + previous_hash chaining
  * PrecedentReference payload construction (fake promotions row + fake hub
    thread JSON): no rationale field anywhere, holding exact, contextHash
    reproducible and equal to the hash of the declared context
  * request validation: production-only eligibility (409), sealed-promotion
    requirement (409), rounds cap, provider/model defaults
  * job registry lifecycle + a thread-safety smoke
  * complete() error guards (no key / no package / unknown provider) — the
    live-model path is NEVER exercised here
  * orchestration integration with a fake complete() and the REAL gate
    subprocess (gate template + run-keys are zero-dep; skipped when node or
    the template checkout is missing), REAL monorepo CLI verify
  * verify FAIL is a displayed result, not an error path
  * gate refusal surfaces as GateRejectionRecorded in the job stream and is
    never swallowed

Live hub calls and live model calls never happen in this file.
"""
import copy
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import challenge

NODE = shutil.which(challenge.NODE)
TOOLING = bool(
    NODE
    and os.path.exists(challenge.GATE_TEMPLATE)
    and os.path.exists(challenge.RUN_KEYS)
)
CLI = TOOLING and os.path.exists(challenge.PROTOCOL_CLI)

SCHEMA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")


class TestToolingPresence(unittest.TestCase):
    """Missing tooling must be a LOUD failure, not a silent green skip.

    This studio suite has no tool-less CI runner — it runs on the dev
    machine, where the challenge feature itself requires node + the protocol
    tooling at runtime. So: this sentinel FAILS (naming exactly what is
    missing and how to override) whenever the tooling is absent; the
    integration classes below still carry skipUnless so a broken environment
    produces ONE precise failure instead of a cascade of misleading ones."""

    def test_challenge_tooling_available(self):
        missing = []
        if not NODE:
            missing.append(f"node executable '{challenge.NODE}' (set CLISTA_NODE)")
        for label, path, env in (
            ("gate template", challenge.GATE_TEMPLATE, "CHALLENGE_GATE_TEMPLATE"),
            ("run-keys.mjs", challenge.RUN_KEYS, "CLISTA_RUN_KEYS"),
            ("protocol CLI", challenge.PROTOCOL_CLI, "CLISTA_PROTOCOL_CLI"),
        ):
            if not os.path.exists(path):
                missing.append(f"{label} at {path} (set {env} or CLISTA_PROTOCOL_ROOT)")
        self.assertFalse(
            missing,
            "challenge tooling missing — the integration tests below are "
            "SKIPPING, which this sentinel refuses to let pass silently:\n  "
            + "\n  ".join(missing))


class TestProtocolRootProbe(unittest.TestCase):
    """The default protocol root prefers the MAIN checkout once the phase-5
    tooling has merged there, falling back to the phase5-topology worktree
    while it exists. The root is all-or-nothing: main's CLI predates T2b
    until the merge lands, so mixing roots is never allowed."""

    def test_prefers_first_candidate_with_gate_tooling(self):
        with tempfile.TemporaryDirectory() as tmp:
            bare = os.path.join(tmp, "bare")
            tooled = os.path.join(tmp, "tooled")
            os.makedirs(os.path.join(bare, "scripts"))
            os.makedirs(os.path.join(tooled, "scripts"))
            for name in ("gate.py", "run-keys.mjs"):
                with open(os.path.join(tooled, "scripts", name), "w") as f:
                    f.write("# marker\n")
            with patch.object(challenge, "_PROTOCOL_ROOT_CANDIDATES", (bare, tooled)):
                self.assertEqual(challenge._default_protocol_root(), tooled)
            with patch.object(challenge, "_PROTOCOL_ROOT_CANDIDATES", (tooled, bare)):
                self.assertEqual(challenge._default_protocol_root(), tooled)

    def test_falls_back_to_first_candidate_when_none_tooled(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
            with patch.object(challenge, "_PROTOCOL_ROOT_CANDIDATES", (a, b)):
                self.assertEqual(challenge._default_protocol_root(), a)

    def test_live_default_root_actually_carries_the_tooling(self):
        # Whatever the probe picked on this machine must hold the files the
        # feature shells to — the loud sentinel above depends on it.
        self.assertTrue(os.path.exists(challenge.GATE_TEMPLATE),
                        challenge.GATE_TEMPLATE)
        self.assertTrue(os.path.exists(challenge.RUN_KEYS), challenge.RUN_KEYS)


def _memory_db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    return conn


def _seed_prompt(conn, pid="fraud-analyst", version="1.0.0", status="production",
                 promotion_slug="fraud-analyst-promo", resolved_at="2026-07-10T00:00:00Z"):
    conn.execute(
        "INSERT INTO prompts (id, version, status, body) VALUES (?,?,?,?)",
        (pid, version, status, f"You are the {pid} role prompt body."))
    if promotion_slug:
        conn.execute(
            """INSERT INTO promotions (prompt_id, version, state, opened_at,
               closes_at, resolved_at, thread_slug, citation_hash, sealed)
               VALUES (?,?,?,?,?,?,?,?,1)""",
            (pid, version, "promoted", "2026-07-09T00:00:00Z",
             "2026-07-10T00:00:00Z", resolved_at, promotion_slug, "sha256:" + "cd" * 32))
    conn.commit()


CLAIM_HASH = "sha256:" + "ab" * 32

FAKE_THREAD_JSON = [
    {"hub": "threadhub.record.v0", "thread": "th_promo_1", "seq": 0,
     "kind": "clista.event",
     "payload": {"event_type": "ThreadCreated", "content_hash": "sha256:" + "11" * 32}},
    {"hub": "threadhub.record.v0", "thread": "th_promo_1", "seq": 1,
     "kind": "clista.event",
     "payload": {"event_type": "ClaimCreated", "content_hash": CLAIM_HASH}},
]


def _request(scenario="Should we raise the fraud threshold?", rounds=2):
    return {
        "scenario": scenario,
        "rounds": rounds,
        "roles": {
            "maker": {"prompt_id": "fraud-analyst", "version": "1.0.0"},
            "checker": {"prompt_id": "fraud-analyst", "version": "1.0.0"},
        },
    }


# ── canonical hashing ────────────────────────────────────────────────


class TestContentHash(unittest.TestCase):
    def test_fixture_vector_matches_integrity_js(self):
        # Computed with packages/protocol/src/integrity.js contentHash on this
        # exact object. Canonicalization drift breaks this vector first.
        ev = {
            "event_id": "evt_test_1",
            "event_type": "ThreadCreated",
            "thread_id": "thr_x",
            "actor_id": "par_orchestrator",
            "timestamp": "2026-07-12T00:00:00.000Z",
            "payload": {"thread": {"id": "thr_x", "title": "t — dash", "question": "q?"}},
            "protocol_version": "clista.protocol.v0",
            "hash_version": "clista.event_hash.v1",
        }
        self.assertEqual(
            challenge.content_hash(ev),
            "sha256:a461283e87faae00bd5c18eadb41b3dcb3d584d26d88dc432a356eb76a48f2dc")

    def test_key_order_is_immaterial(self):
        self.assertEqual(challenge.content_hash({"b": 1, "a": [2, {"z": 0, "y": 1}]}),
                         challenge.content_hash({"a": [2, {"y": 1, "z": 0}], "b": 1}))

    def test_none_values_dropped_like_undefined(self):
        # integrity.js sortKeys drops undefined-valued keys; our port drops None.
        self.assertEqual(challenge.stable_stringify({"a": 1, "b": None}),
                         challenge.stable_stringify({"a": 1}))


class TestMakeEvent(unittest.TestCase):
    def test_first_event_has_no_previous_hash(self):
        ev = challenge.make_event("ThreadCreated", "thr_1", "par_x", {"k": "v"})
        self.assertNotIn("previous_hash", ev)
        self.assertTrue(ev["content_hash"].startswith("sha256:"))
        self.assertEqual(ev["hash_version"], "clista.event_hash.v1")
        self.assertEqual(ev["protocol_version"], "clista.protocol.v0")

    def test_content_hash_excludes_previous_hash_v1(self):
        a = challenge.make_event("PositionTaken", "thr_1", "par_x", {"k": "v"},
                                 at="2026-07-12T00:00:00.000Z", event_id="evt_a")
        b = challenge.make_event("PositionTaken", "thr_1", "par_x", {"k": "v"},
                                 at="2026-07-12T00:00:00.000Z", event_id="evt_a",
                                 previous_hash="sha256:" + "00" * 32)
        self.assertEqual(a["content_hash"], b["content_hash"])
        self.assertEqual(b["previous_hash"], "sha256:" + "00" * 32)


# ── PrecedentReference ───────────────────────────────────────────────


class TestPrecedentReference(unittest.TestCase):
    def _cfg(self):
        return {
            "scenario": "Should we raise the fraud threshold?",
            "rounds": 2,
            "roles": {
                "maker": {"prompt_id": "fraud-analyst", "version": "1.0.0",
                          "provider": "anthropic", "model": "claude-sonnet-5",
                          "body": "maker body",
                          "promotion": {"thread_slug": "fraud-analyst-promo",
                                        "resolved_at": "2026-07-10T00:00:00Z"}},
                "checker": {"prompt_id": "fraud-analyst", "version": "1.0.0",
                            "provider": "anthropic", "model": "claude-sonnet-5",
                            "body": "checker body",
                            "promotion": {"thread_slug": "fraud-analyst-promo",
                                          "resolved_at": "2026-07-10T00:00:00Z"}},
            },
        }

    def test_payload_shape(self):
        cfg = self._cfg()
        ctx = challenge.declared_run_context(cfg)
        payload = challenge.build_precedent_reference(
            "maker", cfg["roles"]["maker"], FAKE_THREAD_JSON, ctx,
            reused_at="2026-07-12T00:00:00Z")
        ref = payload["precedentReference"]
        self.assertEqual(ref["holding"], "prompt fraud-analyst@1.0.0 is production")
        self.assertEqual(ref["sourceEventHash"], CLAIM_HASH)
        self.assertEqual(ref["sourceThreadId"], "th_promo_1")
        self.assertEqual(ref["precedentDate"], "2026-07-10T00:00:00Z")
        self.assertEqual(ref["reusedAt"], "2026-07-12T00:00:00Z")
        self.assertEqual(ref["regrounding"], "fresh")
        self.assertEqual(ref["reusedByParticipantId"], challenge.ORCH_PARTICIPANT)
        self.assertTrue(ref["id"])

    def test_no_rationale_anywhere(self):
        cfg = self._cfg()
        payload = challenge.build_precedent_reference(
            "maker", cfg["roles"]["maker"], FAKE_THREAD_JSON,
            challenge.declared_run_context(cfg))
        flat = json.dumps(payload).lower()
        self.assertNotIn("rationale", flat)
        self.assertNotIn("rationale", payload["precedentReference"])
        self.assertNotIn("sourceRationale", payload["precedentReference"])

    def test_context_hash_reproducible_and_declared(self):
        cfg = self._cfg()
        ctx = challenge.declared_run_context(cfg)
        p1 = challenge.build_precedent_reference("maker", cfg["roles"]["maker"],
                                                 FAKE_THREAD_JSON, ctx)
        p2 = challenge.build_precedent_reference("maker", cfg["roles"]["maker"],
                                                 FAKE_THREAD_JSON, ctx)
        self.assertEqual(p1["precedentReference"]["contextHash"],
                         p2["precedentReference"]["contextHash"])
        # The declaration travels beside the reference, and the hash IS the
        # hash of that declaration — checkable by anyone holding the event.
        self.assertEqual(p1["declaredContext"], ctx)
        self.assertEqual(p1["precedentReference"]["contextHash"],
                         challenge.content_hash(ctx))

    def test_declared_context_shape(self):
        ctx = challenge.declared_run_context(self._cfg())
        self.assertEqual(set(ctx), {"scenario_hash", "roles", "rounds"})
        self.assertEqual(set(ctx["roles"]), {"maker", "checker"})
        self.assertEqual(set(ctx["roles"]["maker"]), {"prompt_id", "version", "model"})
        self.assertTrue(ctx["scenario_hash"].startswith("sha256:"))

    def test_missing_claim_created_is_an_error(self):
        cfg = self._cfg()
        with self.assertRaises(challenge.ChallengeError):
            challenge.build_precedent_reference(
                "maker", cfg["roles"]["maker"], [FAKE_THREAD_JSON[0]],
                challenge.declared_run_context(cfg))


# ── request validation ───────────────────────────────────────────────


class TestValidateRequest(unittest.TestCase):
    def test_valid_request_fills_defaults(self):
        conn = _memory_db()
        _seed_prompt(conn)
        cfg = challenge.validate_request(conn, _request())
        self.assertEqual(cfg["rounds"], 2)
        for role in ("maker", "checker"):
            self.assertEqual(cfg["roles"][role]["provider"], "anthropic")
            self.assertEqual(cfg["roles"][role]["model"], challenge.DEFAULT_MODEL)
            self.assertIn("role prompt body", cfg["roles"][role]["body"])
            self.assertEqual(cfg["roles"][role]["promotion"]["thread_slug"],
                             "fraud-analyst-promo")

    def test_non_production_prompt_is_409(self):
        conn = _memory_db()
        _seed_prompt(conn, status="draft")
        with self.assertRaises(challenge.ChallengeError) as ctx:
            challenge.validate_request(conn, _request())
        self.assertEqual(ctx.exception.status, 409)

    def test_production_without_sealed_promotion_is_409(self):
        # Seeded-production without a promotion thread cannot be cited as
        # precedent — refuse loudly rather than inline the prompt silently.
        conn = _memory_db()
        _seed_prompt(conn, promotion_slug=None)
        with self.assertRaises(challenge.ChallengeError) as ctx:
            challenge.validate_request(conn, _request())
        self.assertEqual(ctx.exception.status, 409)

    def test_unknown_prompt_is_409(self):
        conn = _memory_db()
        with self.assertRaises(challenge.ChallengeError) as ctx:
            challenge.validate_request(conn, _request())
        self.assertEqual(ctx.exception.status, 409)

    def test_rounds_capped_and_validated(self):
        conn = _memory_db()
        _seed_prompt(conn)
        self.assertEqual(challenge.validate_request(conn, _request(rounds=4))["rounds"], 4)
        for bad in (0, 5, "x", -1, 2.5):
            with self.assertRaises(challenge.ChallengeError) as ctx:
                challenge.validate_request(conn, _request(rounds=bad))
            self.assertEqual(ctx.exception.status, 422)

    def test_empty_scenario_is_422(self):
        conn = _memory_db()
        _seed_prompt(conn)
        with self.assertRaises(challenge.ChallengeError) as ctx:
            challenge.validate_request(conn, _request(scenario="   "))
        self.assertEqual(ctx.exception.status, 422)

    def test_unknown_provider_is_422(self):
        conn = _memory_db()
        _seed_prompt(conn)
        req = _request()
        req["roles"]["maker"]["provider"] = "definitely-not-a-provider"
        with self.assertRaises(challenge.ChallengeError) as ctx:
            challenge.validate_request(conn, req)
        self.assertEqual(ctx.exception.status, 422)


# ── job registry ─────────────────────────────────────────────────────


class TestJobRegistry(unittest.TestCase):
    def test_lifecycle(self):
        job_id = challenge.create_job({"rounds": 2})
        snap = challenge.get_job(job_id)
        self.assertEqual(snap["status"], "running")
        self.assertEqual(snap["events"], [])
        challenge.job_event(job_id, "PositionTaken", "MAKER", "took a position",
                            event_hash="sha256:" + "aa" * 32)
        challenge.job_update(job_id, stage="turns")
        snap = challenge.get_job(job_id)
        self.assertEqual(snap["stage"], "turns")
        self.assertEqual(len(snap["events"]), 1)
        self.assertEqual(snap["events"][0]["type"], "PositionTaken")

    def test_unknown_job_is_none(self):
        self.assertIsNone(challenge.get_job("nope"))

    def test_snapshot_is_isolated(self):
        job_id = challenge.create_job({})
        snap = challenge.get_job(job_id)
        snap["status"] = "vandalized"
        snap["events"].append({"type": "Fake"})
        clean = challenge.get_job(job_id)
        self.assertEqual(clean["status"], "running")
        self.assertEqual(clean["events"], [])

    def test_thread_safety_smoke(self):
        job_id = challenge.create_job({})

        def hammer():
            for i in range(50):
                challenge.job_event(job_id, "T", "A", f"e{i}")
                challenge.get_job(job_id)

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(challenge.get_job(job_id)["events"]), 400)


# ── completion helper guards (never a live call) ─────────────────────


class TestComplete(unittest.TestCase):
    def test_anthropic_missing_key_is_503(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with self.assertRaises(challenge.ChallengeError) as ctx:
                challenge.complete("anthropic", "claude-sonnet-5", "sys", [])
            self.assertEqual(ctx.exception.status, 503)

    def test_anthropic_missing_package_is_503(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            with patch.object(challenge, "anthropic", None):
                with self.assertRaises(challenge.ChallengeError) as ctx:
                    challenge.complete("anthropic", "claude-sonnet-5", "sys", [])
                self.assertEqual(ctx.exception.status, 503)

    def test_openai_compat_missing_key_is_503(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with self.assertRaises(challenge.ChallengeError) as ctx:
                challenge.complete("openai", "gpt-4o", "sys", [])
            self.assertEqual(ctx.exception.status, 503)

    def test_unknown_provider_rejected(self):
        with self.assertRaises(challenge.ChallengeError) as ctx:
            challenge.complete("mystery", "m", "sys", [])
        self.assertEqual(ctx.exception.status, 400)

    def test_anthropic_call_carries_timeout_and_joins_text(self):
        # A hung completion must never park the daemon worker forever: the
        # client is constructed with an explicit timeout. Fully mocked SDK —
        # no live call.
        fake_sdk = MagicMock()
        block = MagicMock()
        block.type = "text"
        block.text = "hello"
        fake_sdk.Anthropic.return_value.messages.create.return_value.content = [block]
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}), \
             patch.object(challenge, "anthropic", fake_sdk):
            out = challenge.complete("anthropic", "claude-sonnet-5", "sys",
                                     [{"role": "user", "content": "x"}])
        self.assertEqual(out, "hello")
        fake_sdk.Anthropic.assert_called_once_with(
            api_key="test-key", timeout=challenge.COMPLETION_TIMEOUT)
        create_kwargs = fake_sdk.Anthropic.return_value.messages.create.call_args.kwargs
        self.assertEqual(create_kwargs["model"], "claude-sonnet-5")
        self.assertEqual(create_kwargs["system"], "sys")


# ── orchestration: fake complete(), REAL gate subprocess ─────────────


SCRIPTED = {
    "maker": ["Raise the threshold to 900 for the window.",
              "I hold my position with monitoring added.",
              "FINAL: raise to 875 with daily review."],
    "checker": ["Objection: last year fraud rose 3x during promotions.",
                "Objection: model AUC is stale (5 months)."],
}


def _scripted_complete():
    counters = {"maker": 0, "checker": 0}

    def fake(provider, model, system, messages):
        role = "maker" if "maker" in system.lower() else "checker"
        script = SCRIPTED[role]
        text = script[min(counters[role], len(script) - 1)]
        counters[role] += 1
        return text

    return fake


@unittest.skipUnless(TOOLING, "node + gate template + run-keys required")
class TestRunChallengeIntegration(unittest.TestCase):
    """The integration that matters: the run drives the REAL keyed gate
    (subprocess, temp run dir), then the REAL monorepo CLI verify. Model,
    hub, and anchor layers are faked."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="challenge-test-")
        cls.runs_dir = os.path.join(cls.tmp, "challenge_runs")
        conn = _memory_db()
        _seed_prompt(conn)
        cfg = challenge.validate_request(conn, _request())
        conn.close()
        cls.job_id = challenge.create_job({"rounds": cfg["rounds"]})

        cls.anchor_receipt = {
            "schema": "clista.anchor_receipt.v0", "thread": "th_run_1",
            "slug": "challenge-run-slug", "head": "sha256:" + "ee" * 32,
            "completed": True, "landed": 12, "total": 12, "valid": True,
        }

        def fake_run_anchor(run_dir, title, question):
            return dict(cls.anchor_receipt)

        with patch.object(challenge, "RUNS_DIR", cls.runs_dir), \
             patch.object(challenge, "complete", _scripted_complete()), \
             patch.object(challenge, "_hub_thread_json",
                          lambda slug: list(FAKE_THREAD_JSON)), \
             patch.object(challenge, "run_anchor", fake_run_anchor), \
             patch.object(challenge.anchors, "anchor_seal",
                          lambda slug, **kw: {"anchored": True, "anchor_pushed": False,
                                              "anchor_push_error": "test: no remote"}):
            challenge.run_job(cls.job_id, cfg)
        cls.snap = challenge.get_job(cls.job_id)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _run_dir(self):
        return self.snap["result"]["run_dir"]

    def _gate_events(self):
        with open(os.path.join(self._run_dir(), "thread.jsonl")) as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_job_done(self):
        self.assertIsNone(self.snap["error"], msg=json.dumps(self.snap, indent=2))
        self.assertEqual(self.snap["status"], "done")

    def test_gate_thread_sealed_and_ordered(self):
        events = self._gate_events()
        types = [e["type"] for e in events]
        self.assertEqual(types[0], "ThreadOpened")
        self.assertEqual(types.count("WriterRegistered"), 2)
        self.assertEqual(types[-1], "ThreadSealed")
        self.assertEqual(types[-2], "SealedReport")
        # Both PrecedentReference events precede the first turn.
        first_turn = types.index("PositionTaken")
        precedent_idx = [i for i, t in enumerate(types) if t == "PrecedentReference"]
        self.assertEqual(len(precedent_idx), 2)
        self.assertTrue(all(i < first_turn for i in precedent_idx))
        # Every event was signed at append time.
        self.assertTrue(all(e.get("sig") for e in events))

    def test_turn_events_witnessed_by_their_writers(self):
        events = self._gate_events()
        self.assertEqual(
            sum(1 for e in events if e["writer"] == "MAKER" and e["type"] == "PositionTaken"), 2)
        self.assertEqual(
            sum(1 for e in events if e["writer"] == "CHECKER" and e["type"] == "ObjectionRaised"), 2)
        self.assertEqual(
            sum(1 for e in events if e["writer"] == "MAKER" and e["type"] == "ClaimCreated"), 1)

    def test_clista_log_chains(self):
        path = os.path.join(self._run_dir(), "events.ndjson")
        with open(path) as f:
            events = [json.loads(line) for line in f if line.strip()]
        prev = None
        for ev in events:
            material = {k: v for k, v in ev.items()
                        if k not in ("content_hash", "previous_hash")}
            self.assertEqual(ev["content_hash"], challenge.content_hash(material))
            if prev is None:
                self.assertNotIn("previous_hash", ev)
            else:
                self.assertEqual(ev["previous_hash"], prev)
            prev = ev["content_hash"]
        self.assertEqual(events[-1]["event_type"], "SealedReport")

    @unittest.skipUnless(CLI, "monorepo protocol CLI required")
    def test_three_verdicts_pass(self):
        result = self.snap["result"]
        self.assertEqual(result["verdicts"],
                         {"chain": "PASS", "coverage": "PASS", "curation": "PASS"})
        self.assertIn("PASS", result["verify_raw"])

    def test_report_cites_dissent_or_discloses(self):
        events = self._gate_events()
        report = next(e for e in events if e["type"] == "SealedReport")
        sealed = report["payload"]["payload"]["sealedReport"]
        cited = {h for c in sealed["claims"] for h in c["citedEventHashes"]}
        disclosed = {o["eventHash"] for o in sealed.get("omitted_dissent", [])}
        for e in events:
            if e["type"] in ("PositionTaken", "ObjectionRaised"):
                ch = e["payload"]["content_hash"]
                self.assertIn(ch, cited | disclosed)

    def test_keys_are_0600_and_never_in_job(self):
        keys_dir = os.path.join(self._run_dir(), "keys")
        pems = [f for f in os.listdir(keys_dir) if f.endswith(".pem")]
        self.assertEqual(len(pems), 3)
        for pem in pems:
            mode = stat.S_IMODE(os.stat(os.path.join(keys_dir, pem)).st_mode)
            self.assertEqual(mode, 0o600, f"{pem} mode {oct(mode)}")
        flat = json.dumps(self.snap)
        self.assertNotIn("PRIVATE KEY", flat)
        self.assertNotIn("BEGIN", flat)

    def test_result_carries_hub_and_anchor(self):
        result = self.snap["result"]
        self.assertEqual(result["hub"]["slug"], "challenge-run-slug")
        self.assertEqual(result["hub"]["head"], self.anchor_receipt["head"])
        self.assertTrue(result["anchor"]["anchored"])
        self.assertIn("disclosure", result["anchor"])
        self.assertTrue(result["report_hash"].startswith("sha256:"))

    def test_job_event_stream_populated(self):
        types = {e["type"] for e in self.snap["events"]}
        for expected in ("ThreadOpened", "WriterRegistered", "PrecedentReference",
                         "PositionTaken", "ObjectionRaised", "SealedReport",
                         "ThreadSealed"):
            self.assertIn(expected, types)


@unittest.skipUnless(TOOLING, "node + gate template + run-keys required")
class TestGateRefusal(unittest.TestCase):
    def test_append_to_sealed_thread_is_a_recorded_refusal(self):
        tmp = tempfile.mkdtemp(prefix="challenge-gate-")
        try:
            run_dir = os.path.join(tmp, "run")
            gate = challenge.Gate.create(run_dir)
            with open(os.path.join(run_dir, "genesis_prompt.md"), "w") as f:
                f.write("genesis")
            gate.init(os.path.join(run_dir, "genesis_prompt.md"), "refusal-test")
            gate.seal()
            with self.assertRaises(challenge.GateRejection) as ctx:
                gate.append("ORCHESTRATOR", "PositionTaken", {"x": 1})
            self.assertIn("sealed", str(ctx.exception).lower())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_refusal_surfaces_in_job_stream_and_fails_run(self):
        """A refusal must leave (a) the UI-facing job entry, (b) an IN-LOG
        GateRejectionRecorded witness — signed, chained, committing to the
        refused candidate by content hash, never embedding it — per
        DR-2026-07-12-silent-action-prohibition and the JS harness's
        witnessRejection (src/gate.js), and (c) a failed run."""
        conn = _memory_db()
        _seed_prompt(conn)
        cfg = challenge.validate_request(conn, _request(rounds=1))
        conn.close()
        job_id = challenge.create_job({})
        tmp = tempfile.mkdtemp(prefix="challenge-refuse-")

        real_append = challenge.Gate.append

        def sabotaged(self, writer, etype, payload):
            # Refuse the first MAKER turn only; the witness append (and
            # everything before it) goes through the REAL gate.
            if etype == "PositionTaken":
                raise challenge.GateRejection("GATE REJECT: writer 'MAKER' not registered")
            return real_append(self, writer, etype, payload)

        try:
            with patch.object(challenge, "RUNS_DIR", os.path.join(tmp, "runs")), \
                 patch.object(challenge, "complete", _scripted_complete()), \
                 patch.object(challenge, "_hub_thread_json",
                              lambda slug: list(FAKE_THREAD_JSON)), \
                 patch.object(challenge.Gate, "append", sabotaged):
                challenge.run_job(job_id, cfg)
            snap = challenge.get_job(job_id)
            self.assertEqual(snap["status"], "failed")
            self.assertIn("GATE REJECT", snap["error"]["message"])
            self.assertTrue(snap["error"]["stage"])
            rejections = [e for e in snap["events"]
                          if e["type"] == "GateRejectionRecorded"]
            self.assertEqual(len(rejections), 1)
            self.assertIn("not registered", rejections[0]["summary"])

            # The in-log witness: signed, ORCHESTRATOR-written, in thread.jsonl.
            run_dir = snap["result"]["run_dir"]
            with open(os.path.join(run_dir, "thread.jsonl")) as f:
                gate_events = [json.loads(line) for line in f if line.strip()]
            witnesses = [e for e in gate_events
                         if e["type"] == "GateRejectionRecorded"]
            self.assertEqual(len(witnesses), 1)
            witness = witnesses[0]
            self.assertEqual(witness["writer"], "ORCHESTRATOR")
            self.assertTrue(witness.get("sig"))
            rejection = witness["payload"]["payload"]["gateRejection"]
            self.assertEqual(rejection["candidateEventType"], "PositionTaken")
            self.assertIn("not registered", rejection["reasons"][0]["reason"])
            self.assertEqual(rejection["rejectedByParticipantId"],
                             challenge.ROLE_PARTICIPANT["maker"])
            # Committed by hash, never embedded: the candidate hash matches
            # the one the job stream reported, and the refused statement's
            # text is nowhere in the witness.
            self.assertEqual(rejection["candidateContentHash"],
                             rejections[0]["hash"])
            self.assertNotIn("Raise the threshold", json.dumps(witness))

            # The witness is chained into the ClisTa log too (T2b can hold a
            # later report accountable for it).
            with open(os.path.join(run_dir, "events.ndjson")) as f:
                clista = [json.loads(line) for line in f if line.strip()]
            self.assertEqual(clista[-1]["event_type"], "GateRejectionRecorded")
            self.assertEqual(clista[-1]["previous_hash"],
                             clista[-2]["content_hash"])
            self.assertEqual(snap["result"]["rejectionWitnessed"], True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_unwitnessable_refusal_is_disclosed_not_forced(self):
        """When the witness append is itself refused (here: sealed thread),
        nothing is appended and the job discloses rejectionWitnessed: False —
        the DR's residual boundary: a gate never corrupts (or force-extends)
        a log in order to witness a refusal."""
        tmp = tempfile.mkdtemp(prefix="challenge-sealed-witness-")
        try:
            run_dir = os.path.join(tmp, "run")
            gate = challenge.Gate.create(run_dir)
            with open(os.path.join(run_dir, "genesis_prompt.md"), "w") as f:
                f.write("genesis")
            gate.init(os.path.join(run_dir, "genesis_prompt.md"), "sealed-witness")
            gate.seal()
            with open(os.path.join(run_dir, "thread.jsonl")) as f:
                before = f.read()

            candidate = challenge.make_event(
                "PositionTaken", "thr_x", challenge.ROLE_PARTICIPANT["maker"],
                {"position": {"id": "pos_r1", "statement": "s"}})
            witness = challenge.witness_rejection(
                gate, "thr_x", [], os.path.join(run_dir, "events.ndjson"),
                candidate, "GATE REJECT: thread is sealed; append refused")
            self.assertIsNone(witness)
            with open(os.path.join(run_dir, "thread.jsonl")) as f:
                self.assertEqual(f.read(), before)  # nothing appended
            self.assertFalse(os.path.exists(os.path.join(run_dir, "events.ndjson")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ── verify: FAIL is a result, not an exception ───────────────────────


@unittest.skipUnless(CLI, "monorepo protocol CLI required")
class TestRunVerify(unittest.TestCase):
    def test_fail_is_a_displayed_result(self):
        tmp = tempfile.mkdtemp(prefix="challenge-verify-")
        try:
            tid = "thr_bad"
            e1 = challenge.make_event("ThreadCreated", tid, "par_x", {"a": 1})
            report = {"id": "rpt_bad", "claims": [
                {"text": "cites a ghost", "citedEventHashes": ["sha256:" + "99" * 32]}]}
            e2 = challenge.make_event("SealedReport", tid, "par_x",
                                      {"sealedReport": report},
                                      previous_hash=e1["content_hash"])
            path = os.path.join(tmp, "events.ndjson")
            with open(path, "w") as f:
                for ev in (e1, e2):
                    f.write(json.dumps(ev) + "\n")
            result = challenge.run_verify(path)
            self.assertEqual(result["verdicts"]["chain"], "PASS")
            self.assertEqual(result["verdicts"]["coverage"], "FAIL")
            self.assertEqual(result["verdicts"]["curation"], "PASS")
            self.assertFalse(result["valid"])
            self.assertIn("FAIL", result["verify_raw"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ── demo scenario ────────────────────────────────────────────────────


class TestDemoScenario(unittest.TestCase):
    def test_demo_is_the_fraud_threshold_scenario(self):
        self.assertIn("fraud model auto-declines", challenge.DEMO_SCENARIO)
        self.assertIn("850", challenge.DEMO_SCENARIO)
        self.assertIn("model risk committee", challenge.DEMO_SCENARIO)


if __name__ == "__main__":
    unittest.main()
