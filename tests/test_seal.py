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
        self.assertEqual(out, {"slug": "ship-beta", "citationHash": "sha256:head"})
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
