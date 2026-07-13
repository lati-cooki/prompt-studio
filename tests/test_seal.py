import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import seal


class TestValidatePayload(unittest.TestCase):
    def _valid(self):
        return {
            "title": "Ship beta?",
            "question": "Ship the support beta?",
            "decision": "Ship to redacted tickets only",
            "decidedBy": "Troy",
            "evidence": [{"source": "support logs", "finding": "82% FAQ-shaped"}],
            "objections": [{"text": "Privacy risk remains"}],
        }

    def test_accepts_valid_payload(self):
        out = seal.validate_payload(self._valid())
        self.assertEqual(out["question"], "Ship the support beta?")
        self.assertEqual(out["evidence"], [{"source": "support logs", "finding": "82% FAQ-shaped"}])
        self.assertEqual(out["objections"], ["Privacy risk remains"])

    def test_title_defaults_to_question(self):
        p = self._valid(); del p["title"]
        self.assertEqual(seal.validate_payload(p)["title"], p["question"])

    def test_missing_required_fields_collected(self):
        with self.assertRaises(seal.SealValidationError) as ctx:
            seal.validate_payload({"evidence": []})
        fields = ctx.exception.fields
        self.assertIn("question", fields)
        self.assertIn("decision", fields)
        self.assertIn("decidedBy", fields)
        self.assertIn("evidence", fields)

    def test_evidence_requires_source_and_finding(self):
        p = self._valid(); p["evidence"] = [{"source": "x", "finding": ""}]
        with self.assertRaises(seal.SealValidationError) as ctx:
            seal.validate_payload(p)
        self.assertIn("evidence", ctx.exception.fields)

    def test_non_dict_payload_raises(self):
        with self.assertRaises(seal.SealValidationError):
            seal.validate_payload(["not", "a", "dict"])

    def test_non_dict_evidence_items_skipped(self):
        p = self._valid(); p["evidence"] = ["bad", None, {"source": "s", "finding": "f"}]
        out = seal.validate_payload(p)
        self.assertEqual(out["evidence"], [{"source": "s", "finding": "f"}])

    def test_non_list_evidence_treated_as_missing(self):
        p = self._valid(); p["evidence"] = "oops"
        with self.assertRaises(seal.SealValidationError) as ctx:
            seal.validate_payload(p)
        self.assertIn("evidence", ctx.exception.fields)


def _proc(stdout, returncode=0):
    m = MagicMock()
    m.stdout = stdout
    m.stderr = ""
    m.returncode = returncode
    return m


class TestAuthorClistaLog(unittest.TestCase):
    def _data(self):
        return {
            "title": "Ship?", "question": "Ship?", "decision": "Ship redacted",
            "decidedBy": "Troy",
            "evidence": [{"source": "logs", "finding": "82% FAQ"},
                         {"source": "privacy", "finding": "PII risk"}],
            "objections": ["Privacy risk remains"],
        }

    @patch("seal.subprocess.run")
    def test_authoring_sequence_and_id_threading(self, run):
        run.side_effect = [
            _proc(json.dumps({"thread": {"id": "thd_1"}})),
            _proc(json.dumps({"participant": {"id": "par_troy"}})),
            _proc(json.dumps({"evidence": {"id": "evd_1"}})),
            _proc(json.dumps({"evidence": {"id": "evd_2"}})),
            _proc(json.dumps({"claim": {"id": "clm_1"}})),
            _proc(json.dumps({"objection": {"id": "obj_1"}})),
            _proc(json.dumps({"valid": True, "errors": []})),
        ]
        seal.author_clista_log(self._data(), "/tmp/x")
        calls = [c.args[0] for c in run.call_args_list]
        claim_call = next(a for a in calls if "claim" in a and "create" in a)
        self.assertIn("evd_1,evd_2", claim_call)
        obj_call = next(a for a in calls if "objection" in a and "raise" in a)
        self.assertIn("clm_1", obj_call)
        self.assertIn("validate", calls[-1])

    @patch("seal.subprocess.run")
    def test_validate_failure_raises(self, run):
        run.side_effect = [
            _proc(json.dumps({"thread": {"id": "thd_1"}})),
            _proc(json.dumps({"participant": {"id": "par_troy"}})),
            _proc(json.dumps({"evidence": {"id": "evd_1"}})),
            _proc(json.dumps({"evidence": {"id": "evd_2"}})),
            _proc(json.dumps({"claim": {"id": "clm_1"}})),
            _proc(json.dumps({"objection": {"id": "obj_1"}})),
            _proc(json.dumps({"valid": False, "errors": [{"reason": "bad"}]})),
        ]
        with self.assertRaises(seal.SealError):
            seal.author_clista_log(self._data(), "/tmp/x")

    @patch("seal.subprocess.run")
    def test_non_json_stdout_raises_sealerror(self, run):
        run.return_value = _proc("Usage: clista ...\n")  # non-JSON, returncode 0
        with self.assertRaises(seal.SealError):
            seal.author_clista_log(self._data(), "/tmp/x")

    @patch("seal.subprocess.run")
    def test_missing_key_in_response_raises_sealerror(self, run):
        run.return_value = _proc(json.dumps({"unexpected": True}))  # no thread.id
        with self.assertRaises(seal.SealError):
            seal.author_clista_log(self._data(), "/tmp/x")

    @patch("seal.subprocess.run", side_effect=FileNotFoundError("node"))
    def test_node_missing_raises_sealerror(self, run):
        with self.assertRaises(seal.SealError):
            seal.author_clista_log(self._data(), "/tmp/x")


class _Resp:
    def __init__(self, body):
        self._b = json.dumps(body).encode()
    def read(self):
        return self._b
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


class TestThreadHubWrite(unittest.TestCase):
    @patch("seal.urllib.request.urlopen")
    def test_writes_thread_and_records_then_verifies(self, urlopen):
        urlopen.side_effect = [
            _Resp({"slug": "ship-beta"}),
            _Resp({"record_hash": "sha256:a", "seq": 1}),
            _Resp({"record_hash": "sha256:b", "seq": 2}),
            _Resp({"valid": True, "records": 3, "head": "sha256:head"}),
        ]
        events = os.path.join(os.path.dirname(__file__), "_seal_events.ndjson")
        with open(events, "w") as f:
            f.write(json.dumps({"event_type": "ThreadCreated"}) + "\n")
            f.write(json.dumps({"event_type": "EvidenceCommitted"}) + "\n")
        try:
            out = seal.write_to_threadhub(events, "Ship?", "Ship?", "id_author")
        finally:
            os.remove(events)
        self.assertEqual(out, {"slug": "ship-beta", "citationHash": "sha256:head",
                               "records": [
                                   {"seq": 1, "record_hash": "sha256:a",
                                    "event_type": "ThreadCreated"},
                                   {"seq": 2, "record_hash": "sha256:b",
                                    "event_type": "EvidenceCommitted"},
                               ]})
        self.assertEqual(urlopen.call_count, 4)

    @patch("seal.urllib.request.urlopen",
           side_effect=seal.urllib.error.URLError("refused"))
    def test_threadhub_down_raises_unreachable(self, urlopen):
        events = os.path.join(os.path.dirname(__file__), "_seal_events2.ndjson")
        with open(events, "w") as f:
            f.write(json.dumps({"event_type": "ThreadCreated"}) + "\n")
        try:
            with self.assertRaises(seal.SealError) as ctx:
                seal.write_to_threadhub(events, "t", "q", "id_author")
        finally:
            os.remove(events)
        self.assertEqual(ctx.exception.status, 502)
        self.assertEqual(ctx.exception.extra.get("code"), "threadhub_unreachable")


    @patch("seal.urllib.request.urlopen")
    def test_malformed_event_line_raises_with_partial_slug(self, urlopen):
        urlopen.return_value = _Resp({"slug": "ship"})  # POST /threads succeeds
        events = os.path.join(os.path.dirname(__file__), "_seal_bad.ndjson")
        with open(events, "w") as f:
            f.write("{not json\n")
        try:
            with self.assertRaises(seal.SealError) as ctx:
                seal.write_to_threadhub(events, "t", "q", "id_author")
        finally:
            os.remove(events)
        self.assertEqual(ctx.exception.extra.get("partialSlug"), "ship")

    @patch("seal.urllib.request.urlopen")
    def test_non_json_200_raises_sealerror(self, urlopen):
        class _RawResp:
            def read(self_):
                return b"<html>not json</html>"
            def __enter__(self_):
                return self_
            def __exit__(self_, *a):
                return False
        urlopen.return_value = _RawResp()
        with self.assertRaises(seal.SealError) as ctx:
            seal._th("GET", "/threads")
        self.assertEqual(ctx.exception.status, 502)


def _capture_requests(bodies):
    """Return (urlopen side_effect, captured list). Captures (method, url, data bytes)."""
    captured = []
    responses = [_Resp(b) for b in bodies]

    def side_effect(req, timeout=None):
        captured.append((req.get_method(), req.full_url, req.data))
        return responses.pop(0)

    return side_effect, captured


_EVENT_SEQUENCE = [
    {"event_type": "ThreadCreated", "payload": {}},
    {"event_type": "ParticipantDeclared", "payload": {}},
    {"event_type": "EvidenceCommitted", "payload": {}},
    {"event_type": "ClaimCreated", "payload": {}},
    {"event_type": "ObjectionRaised", "payload": {"n": 0}},
    {"event_type": "ObjectionRaised", "payload": {"n": 1}},
]


def _write_events(path, events=None):
    with open(path, "w") as f:
        for e in (events if events is not None else _EVENT_SEQUENCE):
            f.write(json.dumps(e) + "\n")


def _record_responses(n):
    return ([{"slug": "s"}]
            + [{"record_hash": f"sha256:{i}", "seq": i + 1} for i in range(n)]
            + [{"valid": True, "head": "sha256:head"}])


class TestPerRecordWriterIdentity(unittest.TestCase):
    """Phase 5 slice 2: envelope author varies per record by ClisTa event_type
    (DR 5.2 — semantic author = transport writer)."""

    def _run(self, writers, events=None):
        events_list = events if events is not None else _EVENT_SEQUENCE
        side_effect, captured = _capture_requests(_record_responses(len(events_list)))
        path = os.path.join(os.path.dirname(__file__), "_seal_writer_events.ndjson")
        _write_events(path, events_list)
        try:
            with patch("seal.urllib.request.urlopen", side_effect=side_effect):
                out = seal.write_to_threadhub(path, "T", "Q", writers)
        finally:
            os.remove(path)
        return out, captured

    def test_legacy_string_author_bodies_byte_identical(self):
        """When no writers mapping is passed, every HTTP request body must be
        byte-identical to what the pre-slice-2 implementation emitted."""
        out, captured = self._run("id_legacy")
        # exact bytes the legacy code produced, key order and all
        expected_thread = json.dumps(
            {"title": "T", "question": "Q", "author": "id_legacy"}).encode("utf-8")
        self.assertEqual(captured[0][2], expected_thread)
        for i, event in enumerate(_EVENT_SEQUENCE):
            expected_record = json.dumps(
                {"author": "id_legacy", "kind": "clista.event",
                 "payload": event}).encode("utf-8")
            self.assertEqual(captured[1 + i][2], expected_record)
        self.assertIsNone(captured[-1][2])  # GET /verify has no body

    def test_writers_mapping_varies_author_per_event_type(self):
        writers = {
            "default": "id_operator",
            "claim": "id_claimant",
            "evidence": "id_grader",
            "objections": ["id_obj0", "id_obj1"],
        }
        out, captured = self._run(writers)
        # thread creation (genesis) -> operator
        self.assertEqual(json.loads(captured[0][2])["author"], "id_operator")
        authors = [json.loads(c[2])["author"] for c in captured[1:-1]]
        self.assertEqual(authors, [
            "id_operator",   # ThreadCreated -> default
            "id_operator",   # ParticipantDeclared -> default
            "id_grader",     # EvidenceCommitted -> grader
            "id_claimant",   # ClaimCreated -> claim writer
            "id_obj0",       # 1st ObjectionRaised
            "id_obj1",       # 2nd ObjectionRaised
        ])

    def test_missing_writer_keys_fall_back_to_default(self):
        writers = {"default": "id_operator", "objections": ["id_obj0"]}
        out, captured = self._run(writers)
        authors = [json.loads(c[2])["author"] for c in captured[1:-1]]
        self.assertEqual(authors, [
            "id_operator", "id_operator",
            "id_operator",   # no grader known -> default
            "id_operator",   # no claim writer -> default
            "id_obj0",       # 1st objection has a writer
            "id_operator",   # 2nd objection past the list -> default
        ])

    def test_extended_return_carries_per_record_seq_hash_and_type(self):
        out, captured = self._run({"default": "id_operator"})
        self.assertEqual(out["slug"], "s")
        self.assertEqual(out["citationHash"], "sha256:head")
        self.assertEqual(len(out["records"]), len(_EVENT_SEQUENCE))
        self.assertEqual(out["records"][0],
                         {"seq": 1, "record_hash": "sha256:0",
                          "event_type": "ThreadCreated"})
        self.assertEqual(out["records"][3]["event_type"], "ClaimCreated")
        self.assertEqual(out["records"][5],
                         {"seq": 6, "record_hash": "sha256:5",
                          "event_type": "ObjectionRaised"})


class TestSealDecisionWriters(unittest.TestCase):
    def _payload(self):
        return {
            "question": "Ship?", "decision": "Ship redacted", "decidedBy": "Troy",
            "evidence": [{"source": "logs", "finding": "82% FAQ"}],
            "objections": [],
        }

    @patch("seal.write_to_threadhub",
           return_value={"slug": "s", "citationHash": "h", "records": []})
    @patch("seal.ensure_author")
    @patch("seal.author_clista_log", return_value="/tmp/x/.clista/events.ndjson")
    def test_writers_mapping_passed_through_and_no_legacy_author(self, author, ensure, write):
        writers = {"default": "id_operator", "claim": "id_operator"}
        out = seal.seal_decision(self._payload(), writers=writers)
        ensure.assert_not_called()  # distinct writers replace the shared author
        self.assertEqual(write.call_args[0][3], writers)
        self.assertEqual(out["records"], [])

    @patch("seal.write_to_threadhub",
           return_value={"slug": "s", "citationHash": "h", "records": []})
    @patch("seal.ensure_author", return_value="id_studio")
    @patch("seal.author_clista_log", return_value="/tmp/x/.clista/events.ndjson")
    def test_no_writers_uses_legacy_shared_author(self, author, ensure, write):
        seal.seal_decision(self._payload())
        ensure.assert_called_once()
        self.assertEqual(write.call_args[0][3], "id_studio")


class TestEnsureAuthor(unittest.TestCase):
    def setUp(self):
        self._orig = seal.AUTHOR_CACHE
        seal.AUTHOR_CACHE = os.path.join(os.path.dirname(__file__), "_seal_author_test")
        if os.path.exists(seal.AUTHOR_CACHE):
            os.remove(seal.AUTHOR_CACHE)

    def tearDown(self):
        if os.path.exists(seal.AUTHOR_CACHE):
            os.remove(seal.AUTHOR_CACHE)
        seal.AUTHOR_CACHE = self._orig

    @patch("seal.urllib.request.urlopen")
    def test_creates_and_caches_author(self, urlopen):
        urlopen.return_value = _Resp({"id": "id_new"})
        first = seal.ensure_author()
        second = seal.ensure_author()  # cached; no 2nd POST
        self.assertEqual(first, "id_new")
        self.assertEqual(second, "id_new")
        self.assertEqual(urlopen.call_count, 1)


class TestSealDecision(unittest.TestCase):
    def _payload(self):
        return {
            "question": "Ship?", "decision": "Ship redacted", "decidedBy": "Troy",
            "evidence": [{"source": "logs", "finding": "82% FAQ"}],
            "objections": [],
        }

    @patch("seal.write_to_threadhub", return_value={"slug": "ship", "citationHash": "sha256:h"})
    @patch("seal.ensure_author", return_value="id_author")
    @patch("seal.author_clista_log", return_value="/tmp/x/.clista/events.ndjson")
    def test_happy_path(self, author, ensure, write):
        out = seal.seal_decision(self._payload())
        self.assertEqual(out, {"slug": "ship", "citationHash": "sha256:h"})
        self.assertTrue(author.called and write.called)

    def test_invalid_payload_propagates(self):
        with self.assertRaises(seal.SealValidationError):
            seal.seal_decision({"evidence": []})

    @patch("seal.ensure_author")
    @patch("seal.author_clista_log", side_effect=seal.SealError("ClisTa validation failed"))
    def test_authoring_failure_skips_threadhub(self, author, ensure):
        with self.assertRaises(seal.SealError):
            seal.seal_decision(self._payload())
        ensure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
