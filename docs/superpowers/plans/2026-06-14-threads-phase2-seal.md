# Threads Add-on — Phase 2 ("Seal as Decision") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Seal as decision" flow to the sandbox that turns a 5-field form into a ClisTa-validated decision log and stores it in ThreadHub as a new thread (viewable in the Phase 1 Threads tab).

**Architecture:** A `POST /api/threads/seal` route delegates to an isolated `seal.py` orchestrator: validate payload → author a ClisTa "decision-as-claim" log via the `clista` CLI in a temp dir → `clista validate` (atomicity gate) → custodial HTTP writes to the running ThreadHub sidecar (`POST /threads` + `POST /t/<slug>/records` per event) → return `{slug, citationHash}`. Zero changes to ClisTa or ThreadHub.

**Tech Stack:** Python 3 stdlib (`http.server`, `subprocess`, `urllib`, `tempfile`), Node CLIs (`clista`, ThreadHub — unchanged), vanilla JS, `unittest` via pytest.

**Spec:** `docs/superpowers/specs/2026-06-14-threads-phase2-seal-design.md`

---

## Verified mechanics (probed against the live tools)

- ClisTa authoring appends to `<cwd>/.clista/events.ndjson`; run each command with `cwd` = a temp dir.
  Each prints the created object as JSON to stdout. Id paths: `thread.id`, `participant.id`,
  `evidence.id`, `claim.id`. Multiple evidence ids on `claim create --evidence` are comma-separated.
- Decision-as-claim sequence validates clean: `thread create` → `participant declare` →
  `evidence commit`(×N) → `claim create --evidence <ids>` → `objection raise --target <claimId>`(×M).
  `clista validate` returns `{valid, errors}` on stdout (exit 1 when invalid — parse stdout, not code).
- ThreadHub HTTP custodial writes (sidecar on `:8110`): `POST /identities {display_name, kind}` → `{id}`;
  `POST /threads {title, question, author}` → `{slug, …}`; `POST /t/<slug>/records {author, kind:"clista.event", payload}` → `{record_hash, seq}`; `GET /t/<slug>/verify` → `{valid, records, head}` (`head` = citation hash).

## File Structure

- **Create** `seal.py` — orchestrator: `validate_payload`, `author_clista_log`, `ensure_author`, `write_to_threadhub`, `seal_decision`, plus `SealValidationError`/`SealError`. CLI paths via env (`CLISTA_CLI`, `THREADHUB_PORT`).
- **Modify** `server.py` — `import seal`; `POST /api/threads/seal` in `do_POST` → `handle_seal`.
- **Modify** `sandbox/index.html` — "Seal as decision" topbar button + modal form + submit JS.
- **Create** `tests/test_seal.py` — unit tests (mock `subprocess.run` + `urllib`).
- **Modify** `tests/test_server.py` — `/api/threads/seal` route test.
- **Modify** `.gitignore` — add `.seal_author_id`.

---

## Task 1: `seal.py` — payload validation

**Files:** Create `seal.py`; Test `tests/test_seal.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_seal.py`:

```python
import os
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/test_seal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'seal'`.

- [ ] **Step 3: Write minimal implementation**

Create `seal.py`:

```python
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

CLISTA_CLI = os.environ.get("CLISTA_CLI", os.path.expanduser("~/ClisTa-Protocol/src/cli.js"))
THREADHUB_PORT = int(os.environ.get("THREADHUB_PORT", "8110"))
AUTHOR_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".seal_author_id")


class SealValidationError(Exception):
    def __init__(self, fields):
        self.fields = fields
        super().__init__("invalid seal payload")


class SealError(Exception):
    def __init__(self, message, status=500, extra=None):
        self.message = message
        self.status = status
        self.extra = extra or {}
        super().__init__(message)


def _s(v):
    return v.strip() if isinstance(v, str) else ""


def validate_payload(payload):
    fields = {}
    question = _s(payload.get("question"))
    decision = _s(payload.get("decision"))
    decided_by = _s(payload.get("decidedBy"))
    if not question:
        fields["question"] = "required"
    if not decision:
        fields["decision"] = "required"
    if not decided_by:
        fields["decidedBy"] = "required"

    evidence = []
    for e in (payload.get("evidence") or []):
        source, finding = _s(e.get("source")), _s(e.get("finding"))
        if source and finding:
            evidence.append({"source": source, "finding": finding})
    if not evidence:
        fields["evidence"] = "at least one evidence item (source + finding) required"

    objections = []
    for o in (payload.get("objections") or []):
        text = _s(o.get("text")) if isinstance(o, dict) else _s(o)
        if text:
            objections.append(text)

    if fields:
        raise SealValidationError(fields)

    return {
        "title": _s(payload.get("title")) or question,
        "question": question,
        "decision": decision,
        "decidedBy": decided_by,
        "evidence": evidence,
        "objections": objections,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/test_seal.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add seal.py tests/test_seal.py
git commit -m "feat(seal): payload validation for decision sealing"
```

---

## Task 2: `seal.py` — ClisTa authoring + validate gate

**Files:** Modify `seal.py`; Test `tests/test_seal.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_seal.py` (top: `from unittest.mock import patch, MagicMock`):

```python
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
            _proc(json.dumps({"valid": True, "errors": []})),  # validate
        ]
        seal.author_clista_log(self._data(), "/tmp/x")
        calls = [c.args[0] for c in run.call_args_list]
        # claim create cites both evidence ids, comma-joined
        claim_call = next(a for a in calls if a[1] == "claim")
        self.assertIn("evd_1,evd_2", claim_call)
        # objection targets the claim id
        obj_call = next(a for a in calls if a[1] == "objection")
        self.assertIn("clm_1", obj_call)
        # validate ran last
        self.assertEqual(calls[-1][1], "validate")

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/test_seal.py::TestAuthorClistaLog -v`
Expected: FAIL — `AttributeError: module 'seal' has no attribute 'author_clista_log'`.

- [ ] **Step 3: Write minimal implementation**

Add to `seal.py`:

```python
def _clista(args, cwd):
    proc = subprocess.run(["node", CLISTA_CLI] + args, cwd=cwd,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise SealError(f"clista {' '.join(args[:2])} failed: {detail}")
    return json.loads(proc.stdout)


def _clista_validate(cwd):
    # validate exits 1 when invalid but still prints JSON to stdout.
    proc = subprocess.run(["node", CLISTA_CLI, "validate"], cwd=cwd,
                          capture_output=True, text=True)
    return json.loads(proc.stdout)


def author_clista_log(data, cwd):
    """Author the decision-as-claim log in <cwd>/.clista; return the events.ndjson path."""
    tid = _clista(["thread", "create", "--title", data["title"],
                   "--question", data["question"]], cwd)["thread"]["id"]
    pid = _clista(["participant", "declare", "--name", data["decidedBy"],
                   "--thread", tid], cwd)["participant"]["id"]
    evidence_ids = []
    for e in data["evidence"]:
        ev = _clista(["evidence", "commit", "--thread", tid,
                      "--source", e["source"], "--finding", e["finding"]], cwd)
        evidence_ids.append(ev["evidence"]["id"])
    cid = _clista(["claim", "create", "--thread", tid, "--text", data["decision"],
                   "--evidence", ",".join(evidence_ids)], cwd)["claim"]["id"]
    for text in data["objections"]:
        _clista(["objection", "raise", "--thread", tid, "--participant", pid,
                 "--target", cid, "--text", text], cwd)
    result = _clista_validate(cwd)
    if not result.get("valid"):
        raise SealError("ClisTa validation failed", extra={"errors": result.get("errors")})
    return os.path.join(cwd, ".clista", "events.ndjson")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/test_seal.py::TestAuthorClistaLog -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add seal.py tests/test_seal.py
git commit -m "feat(seal): author decision-as-claim ClisTa log with validate gate"
```

---

## Task 3: `seal.py` — custodial ThreadHub writes

**Files:** Modify `seal.py`; Test `tests/test_seal.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_seal.py`:

```python
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
            _Resp({"slug": "ship-beta"}),     # POST /threads
            _Resp({"record_hash": "sha256:a", "seq": 1}),  # record 1
            _Resp({"record_hash": "sha256:b", "seq": 2}),  # record 2
            _Resp({"valid": True, "records": 3, "head": "sha256:head"}),  # verify
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/test_seal.py::TestThreadHubWrite -v`
Expected: FAIL — `AttributeError: module 'seal' has no attribute 'write_to_threadhub'`.

- [ ] **Step 3: Write minimal implementation**

Add to `seal.py`:

```python
def _th(method, path, body=None):
    url = f"http://localhost:{THREADHUB_PORT}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        status = 429 if e.code == 429 else 502
        raise SealError(f"ThreadHub {method} {path} returned {e.code}",
                        status=status, extra={"code": "threadhub_http_error"})
    except urllib.error.URLError:
        raise SealError("ThreadHub is not reachable", status=502,
                        extra={"code": "threadhub_unreachable"})


def ensure_author():
    if os.path.exists(AUTHOR_CACHE):
        with open(AUTHOR_CACHE) as f:
            cached = f.read().strip()
        if cached:
            return cached
    author_id = _th("POST", "/identities",
                    {"display_name": "Prompt Studio", "kind": "agent"})["id"]
    with open(AUTHOR_CACHE, "w") as f:
        f.write(author_id)
    return author_id


def write_to_threadhub(events_path, title, question, author_id):
    slug = _th("POST", "/threads",
               {"title": title, "question": question, "author": author_id})["slug"]
    try:
        with open(events_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                _th("POST", f"/t/{slug}/records",
                    {"author": author_id, "kind": "clista.event",
                     "payload": json.loads(line)})
    except SealError as e:
        e.extra["partialSlug"] = slug
        raise
    verify = _th("GET", f"/t/{slug}/verify")
    return {"slug": slug, "citationHash": verify.get("head")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/test_seal.py::TestThreadHubWrite -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add seal.py tests/test_seal.py
git commit -m "feat(seal): custodial ThreadHub HTTP writes + author identity caching"
```

---

## Task 4: `seal.py` — `seal_decision` orchestration

**Files:** Modify `seal.py`; Test `tests/test_seal.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_seal.py`:

```python
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
        # author + validate happen before any ThreadHub write
        self.assertTrue(author.called and write.called)

    def test_invalid_payload_propagates(self):
        with self.assertRaises(seal.SealValidationError):
            seal.seal_decision({"evidence": []})

    @patch("seal.ensure_author")
    @patch("seal.author_clista_log", side_effect=seal.SealError("ClisTa validation failed"))
    def test_authoring_failure_skips_threadhub(self, author, ensure):
        with self.assertRaises(seal.SealError):
            seal.seal_decision(self._payload())
        ensure.assert_not_called()  # no ThreadHub interaction after author failure
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/test_seal.py::TestSealDecision -v`
Expected: FAIL — `AttributeError: module 'seal' has no attribute 'seal_decision'`.

- [ ] **Step 3: Write minimal implementation**

Add to `seal.py`:

```python
def seal_decision(payload):
    data = validate_payload(payload)              # raises SealValidationError
    tmp = tempfile.mkdtemp(prefix="seal-")
    try:
        events_path = author_clista_log(data, tmp)  # author + validate gate (raises on failure)
        author_id = ensure_author()                 # ThreadHub identity (after validate)
        return write_to_threadhub(events_path, data["title"], data["question"], author_id)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/test_seal.py -v`
Expected: PASS (all seal tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add seal.py tests/test_seal.py
git commit -m "feat(seal): orchestrate seal_decision (validate-first, temp-dir lifecycle)"
```

---

## Task 5: `server.py` — `POST /api/threads/seal` route

**Files:** Modify `server.py`; Test `tests/test_server.py`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py`:

```python
class TestSealRoute(unittest.TestCase):
    @patch("seal.seal_decision", return_value={"slug": "ship", "citationHash": "sha256:h"})
    def test_seal_success(self, mock_seal):
        h = MockHandler()
        h.path = "/api/threads/seal"
        h._set_body(json.dumps({"question": "q", "decision": "d", "decidedBy": "Troy",
                                "evidence": [{"source": "s", "finding": "f"}]}).encode())
        h.do_POST()
        self.assertEqual(h._last_status, 200)
        self.assertIn(b"ship", h._body_written)

    @patch("seal.seal_decision", side_effect=__import__("seal").SealValidationError({"question": "required"}))
    def test_seal_validation_error_is_400(self, mock_seal):
        h = MockHandler()
        h.path = "/api/threads/seal"
        h._set_body(json.dumps({}).encode())
        h.do_POST()
        self.assertEqual(h._last_status, 400)
        self.assertIn(b"question", h._body_written)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/test_server.py::TestSealRoute -v`
Expected: FAIL — the `/api/threads/seal` path falls through to 404 (no route), so `assertEqual(200)` fails.

- [ ] **Step 3: Write minimal implementation**

In `server.py`, add to the imports near the top (after `import sqlite3`):

```python
import seal
```

In `do_POST`, add a branch after the existing `elif self.path == '/api/chat':` block:

```python
        elif self.path == '/api/threads/seal':
            self.handle_seal()
```

Add this method to `PromptStudioHandler`:

```python
    def handle_seal(self):
        data = self.read_json_body()
        if data is None:
            return
        try:
            result = seal.seal_decision(data)
        except seal.SealValidationError as e:
            self.send_json({"error": "validation failed", "fields": e.fields}, status=400)
            return
        except seal.SealError as e:
            body = {"error": e.message}
            body.update(e.extra)
            self.send_json(body, status=e.status)
            return
        self.send_json(result, status=200)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/test_server.py::TestSealRoute -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add server.py tests/test_server.py
git commit -m "feat(seal): POST /api/threads/seal route with error mapping"
```

---

## Task 6: Seal form UI (sandbox)

**Files:** Modify `sandbox/index.html`.

- [ ] **Step 1: Add the topbar button**

In `sandbox/index.html`, find the topbar Threads link (added in Phase 1, ~line 698):

```html
      <a class="ghost-btn" href="/threads">Threads</a>
```

Add a Seal button immediately after it:

```html
      <a class="ghost-btn" href="/threads">Threads</a>
      <button type="button" class="ghost-btn" id="seal-open-btn">Seal as decision</button>
```

- [ ] **Step 2: Add the modal markup + script**

Immediately before the closing `</body>` tag in `sandbox/index.html`, add:

```html
<div id="seal-modal" style="display:none;position:fixed;inset:0;background:rgba(12,15,20,.45);z-index:1000;align-items:flex-start;justify-content:center;overflow:auto">
  <div style="background:#f6f3ec;max-width:560px;width:92%;margin:48px 0;padding:24px;border-radius:6px;font-size:13px">
    <h3 style="margin:0 0 12px">Seal as decision</h3>
    <div id="seal-fields">
      <label class="seal-l">Title</label>
      <input id="seal-title" class="seal-i" type="text">
      <label class="seal-l">Question</label>
      <input id="seal-question" class="seal-i" type="text" placeholder="What was being decided?">
      <label class="seal-l">Decision</label>
      <input id="seal-decision" class="seal-i" type="text" placeholder="The yes / statement">
      <label class="seal-l">Evidence <a id="seal-add-ev" href="javascript:void(0)">+ add</a></label>
      <div id="seal-evidence"></div>
      <label class="seal-l">Surviving objection <a id="seal-add-obj" href="javascript:void(0)">+ add</a></label>
      <div id="seal-objections"></div>
      <label class="seal-l">Decided by</label>
      <input id="seal-decidedby" class="seal-i" type="text" value="Troy" style="max-width:220px">
    </div>
    <div id="seal-msg" style="color:#a83830;min-height:18px;margin-top:8px"></div>
    <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:8px">
      <button type="button" class="ghost-btn" id="seal-cancel">Cancel</button>
      <button type="button" class="ghost-btn" id="seal-submit" style="background:#0c0f14;color:#fff">Seal →</button>
    </div>
  </div>
</div>
<style>
  .seal-l{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#5c636b;margin:10px 0 3px}
  .seal-i{width:100%;padding:6px 8px;border:1px solid rgba(12,15,20,.2);border-radius:4px;font:inherit;background:#fff}
  .seal-row{display:flex;gap:6px;margin-bottom:4px}
</style>
<script>
(function () {
  const $ = (id) => document.getElementById(id);
  const modal = $("seal-modal");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function addEvidence() {
    const row = document.createElement("div");
    row.className = "seal-row";
    row.innerHTML = '<input class="seal-i seal-ev-source" placeholder="source" style="flex:1">' +
                    '<input class="seal-i seal-ev-finding" placeholder="finding" style="flex:2">';
    $("seal-evidence").appendChild(row);
  }
  function addObjection() {
    const row = document.createElement("div");
    row.className = "seal-row";
    row.innerHTML = '<input class="seal-i seal-obj-text" placeholder="what was not resolved" style="flex:1">';
    $("seal-objections").appendChild(row);
  }

  function openModal() {
    $("seal-evidence").innerHTML = "";
    $("seal-objections").innerHTML = "";
    addEvidence();
    $("seal-msg").textContent = "";
    $("seal-msg").style.color = "#a83830";
    const sess = document.getElementById("topbar-session");
    $("seal-title").value = sess ? sess.textContent.trim() : "";
    modal.style.display = "flex";
  }
  function closeModal() { modal.style.display = "none"; }

  async function submit() {
    const evidence = Array.from(document.querySelectorAll("#seal-evidence .seal-row")).map(r => ({
      source: r.querySelector(".seal-ev-source").value,
      finding: r.querySelector(".seal-ev-finding").value,
    }));
    const objections = Array.from(document.querySelectorAll("#seal-objections .seal-obj-text"))
      .map(i => ({ text: i.value })).filter(o => o.text.trim());
    const payload = {
      title: $("seal-title").value,
      question: $("seal-question").value,
      decision: $("seal-decision").value,
      decidedBy: $("seal-decidedby").value,
      evidence, objections,
    };
    $("seal-msg").style.color = "#5c636b";
    $("seal-msg").textContent = "Sealing…";
    let res, body;
    try {
      res = await fetch("/api/threads/seal", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      body = await res.json();
    } catch (e) {
      $("seal-msg").style.color = "#a83830";
      $("seal-msg").textContent = "Network error.";
      return;
    }
    if (res.ok) {
      $("seal-msg").style.color = "#2e7048";
      $("seal-msg").innerHTML = "✓ Sealed · " + esc(body.slug) + " · " +
        esc((body.citationHash || "").slice(0, 18)) + "… · " +
        '<a href="/threads">Open in Threads ↗</a>';
    } else if (res.status === 400 && body.fields) {
      $("seal-msg").style.color = "#a83830";
      $("seal-msg").textContent = "Missing: " + Object.keys(body.fields).join(", ");
    } else {
      $("seal-msg").style.color = "#a83830";
      $("seal-msg").textContent = "Could not seal: " + esc(body.error || res.status) +
        (body.code === "threadhub_unreachable" ? " (start ThreadHub via the launcher)" : "");
    }
  }

  $("seal-open-btn").addEventListener("click", openModal);
  $("seal-cancel").addEventListener("click", closeModal);
  $("seal-add-ev").addEventListener("click", addEvidence);
  $("seal-add-obj").addEventListener("click", addObjection);
  $("seal-submit").addEventListener("click", submit);
  modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
})();
</script>
```

- [ ] **Step 2b: Run the full suite to confirm nothing broke**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/ -q`
Expected: all pass (no test regressions; this task is UI-only).

- [ ] **Step 3: Manual smoke (DOM)**

Start the servers (`python3 server.py`; ThreadHub sidecar on :8110). Open `http://localhost:8000/`,
click "Seal as decision", confirm the modal opens with a prefilled Title, one evidence row, "+ add"
adds rows, and Cancel / click-outside closes it.

- [ ] **Step 4: Commit**

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add sandbox/index.html
git commit -m "feat(seal): seal-as-decision modal form in the sandbox"
```

---

## Task 7: `.gitignore` + end-to-end acceptance

**Files:** Modify `.gitignore`; verification only otherwise.

- [ ] **Step 1: Ignore the author cache**

In `.gitignore`, add a line:

```
.seal_author_id
```

Commit:

```bash
cd /Users/troylatimer/DevSwarmProjects/Clista
git add .gitignore
git commit -m "chore(seal): gitignore the cached ThreadHub author id"
```

- [ ] **Step 2: Start the stack**

```bash
# ThreadHub sidecar
cd ~/threadhub && node bin/cli.js serve --port 8110 &
# Studio
cd /Users/troylatimer/DevSwarmProjects/Clista && python3 server.py &
```

- [ ] **Step 3: Seal a decision via the API**

```bash
curl -s -X POST http://localhost:8000/api/threads/seal -H 'Content-Type: application/json' -d '{
  "title": "Ship the support beta?",
  "question": "Should we ship the support-assistant beta?",
  "decision": "Yes — ship to redacted sample tickets only",
  "decidedBy": "Troy",
  "evidence": [{"source": "support logs", "finding": "82% of tickets are FAQ-shaped"},
               {"source": "privacy review", "finding": "PII exposure if unredacted"}],
  "objections": [{"text": "Privacy risk remains for non-redacted tickets"}]
}'
```

Expected: `{"slug": "...", "citationHash": "sha256:..."}`.

- [ ] **Step 4: Confirm it landed and verifies**

```bash
curl -s http://localhost:8000/api/threads | python3 -c "import sys,json;print([t['slug'] for t in json.load(sys.stdin)])"
SLUG=<slug from step 3>
curl -s http://localhost:8000/api/threads/$SLUG/verify | python3 -c "import sys,json;d=json.load(sys.stdin);print('valid:',d['valid'],'records:',d['records'])"
```

Expected: the new slug is in the list; verify reports `valid: True`.

- [ ] **Step 5: Confirm ClisTa projects the decision**

```bash
# the sealed thread's events round-trip back out of ThreadHub and project as a real decision
curl -s http://localhost:8000/api/threads/$SLUG | python3 -c "import sys,json;d=json.load(sys.stdin);print('record kinds:',[r.get('kind') for r in d])"
```

Expected: the chain includes `clista.event` records (the authored ClisTa events).

- [ ] **Step 6: Browser acceptance**

Open `http://localhost:8000/`, click "Seal as decision", fill the form, submit. Confirm the green
"✓ Sealed · <slug> · <hash>… · Open in Threads" result, then click "Open in Threads" and confirm the
new thread appears in the tab with a ✓ chain-valid badge.

- [ ] **Step 7: Full suite green**

Run: `cd /Users/troylatimer/DevSwarmProjects/Clista && python3 -m pytest tests/ -q`
Expected: all pass.

---

## Self-Review

**Spec coverage:**
- Seal form (5 fields, topbar entry, result) → Task 6. ✓
- `seal.py` orchestrator (validate, author, ensure-identity, write) → Tasks 1–4. ✓
- `POST /api/threads/seal` route + error mapping → Task 5. ✓
- Decision-as-claim ClisTa sequence (no decision merge) → Task 2. ✓
- Custodial HTTP writes (POST /threads + records, verify head) → Task 3. ✓
- Validate-first atomicity gate → Task 2 (validate in `author_clista_log`) + Task 4 (ordering). ✓
- Error handling: 400 fields (Task 1+5), 502 unreachable (Task 3+5), partialSlug (Task 3), rate-limit 429 (Task 3 `_th`). ✓
- Testing: `seal.py` unit tests (Tasks 1–4), route test (Task 5), end-to-end (Task 7). ✓
- Non-goals respected: no prefill beyond title, no formal decision merge, no non-custodial signing. ✓
- `.seal_author_id` gitignored → Task 7. ✓

**Placeholder scan:** No TBD/TODO; all steps carry complete code. Step references like "<slug from step 3>" are runtime values in a manual verification step, not code placeholders.

**Type/name consistency:** `validate_payload` → normalized dict with keys `title/question/decision/decidedBy/evidence/objections`, consumed identically by `author_clista_log` and `seal_decision`. `SealValidationError.fields` and `SealError.status/extra` are used consistently across `seal.py` and the `handle_seal` mapping. `write_to_threadhub` returns `{slug, citationHash}` — matched by the route test and the UI.
