"""challenge.py — the Studio Challenge Run (Phase 5 Wave 3 / Slice 7).

Orchestrates a witnessed MAKER/CHECKER deliberation over a scenario, with
every event submitted through the keyed sidecar gate (validate-before-append,
signed at append time — DR-phase5-topology rule 5.1), registry prompts pulled
in as PrecedentReference citations (holding travels, rationale never — the
precedent-as-citation DR), a terminal claim-cited SealedReport, three-verdict
verification (chain / coverage / T2b curation) via the MONOREPO protocol CLI,
signed accumulation to ThreadHub via anchor-run.mjs, and a studio anchor row
(rule 4.1: the anchor row for a studio-emitted run lands in the STUDIO's
ANCHORS.md).

Threading model: the studio server is a single-threaded socketserver.TCPServer,
so the run executes on a threading.Thread(daemon=True). Handlers only create
jobs and read snapshots; all long work happens here on the worker thread. The
worker NEVER shares a sqlite3 connection with the request thread — every DB
need is satisfied before the thread starts (validate_request runs in the
request handler and bakes prompt bodies + promotion rows into the config).

Key hygiene (DR rule 5.5): per-run ed25519 keys are minted by run-keys.mjs
into <run_dir>/keys with the .pem files at 0600. Private key material is never
read into this process, never logged, and never present in job snapshots —
this module only ever handles key file PATHS and public keys.

External tooling paths (post-merge these defaults become the main-checkout
paths; override via env until then):
  CHALLENGE_GATE_TEMPLATE  gate.py template (copied into each run dir — it
                           refuses to run in place from a scripts/ dir)
  CLISTA_RUN_KEYS          run-keys.mjs (keygen/sign/verify; the gate shells
                           to it too)
  CLISTA_PROTOCOL_CLI      the MONOREPO protocol CLI (src/cli.js). NOTE: the
                           legacy CLISTA_CLI used by seal.py does NOT have the
                           T2b curation check; the monorepo CLI does — verify
                           MUST shell to this one.
  CHALLENGE_ANCHOR_RUN     anchor-run.mjs (non-custodial hub accumulation)
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from copy import deepcopy
from datetime import datetime, timezone

import anchors
import seal

try:
    import anthropic
except ImportError:
    anthropic = None

STUDIO_ROOT = os.path.dirname(os.path.abspath(__file__))

# Monorepo worktree (read-only reference checkout). Post-merge, point these
# defaults at the main checkout of the monorepo instead.
_MONOREPO_PROTOCOL = os.environ.get(
    "CLISTA_PROTOCOL_ROOT",
    "/Users/troylatimer/Projects/clista/.claude/worktrees/phase5-topology/packages/protocol")

GATE_TEMPLATE = os.environ.get(
    "CHALLENGE_GATE_TEMPLATE", os.path.join(_MONOREPO_PROTOCOL, "scripts", "gate.py"))
RUN_KEYS = os.environ.get(
    "CLISTA_RUN_KEYS", os.path.join(_MONOREPO_PROTOCOL, "scripts", "run-keys.mjs"))
PROTOCOL_CLI = os.environ.get(
    "CLISTA_PROTOCOL_CLI", os.path.join(_MONOREPO_PROTOCOL, "src", "cli.js"))
ANCHOR_RUN = os.environ.get(
    "CHALLENGE_ANCHOR_RUN", os.path.join(_MONOREPO_PROTOCOL, "scripts", "anchor-run.mjs"))
NODE = os.environ.get("CLISTA_NODE", "node")

# Run directories are git-ignored working artifacts (challenge_runs/ in
# .gitignore); the durable testimony is the hub thread + the studio anchor row.
RUNS_DIR = os.environ.get("CHALLENGE_RUNS_DIR", os.path.join(STUDIO_ROOT, "challenge_runs"))

DEFAULT_PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-sonnet-5"  # owner decision: frontier default
DEFAULT_ROUNDS = 2
MAX_ROUNDS = 4
SUBPROCESS_TIMEOUT = 120  # seconds per gate/CLI call
COMPLETION_TIMEOUT = 300  # seconds per model call

ORCH_PARTICIPANT = "par_challenge_orchestrator"
ROLES = ("maker", "checker")
ROLE_WRITER = {"maker": "MAKER", "checker": "CHECKER"}
ROLE_PARTICIPANT = {"maker": "par_challenge_maker", "checker": "par_challenge_checker"}

# Mirror of server.PromptStudioHandler._OPENAI_COMPAT (challenge cannot import
# server — server imports challenge). Non-streaming endpoints, same env vars.
_OPENAI_COMPAT = {
    "openai": ("https://api.openai.com/v1/chat/completions", "OPENAI_API_KEY"),
    "xai": ("https://api.x.ai/v1/chat/completions", "XAI_API_KEY"),
    "google": ("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
               "GEMINI_API_KEY"),
}

# Copied verbatim from packages/protocol/src/event-types.js
# DISSENT_BEARING_TYPES (DR-2026-07-12-curation-check): the set the T2b
# curation check holds a SealedReport accountable for. The report builder
# below uses it to guarantee no dissent-bearing event is silently omitted.
DISSENT_BEARING_TYPES = frozenset([
    "CompatibilityFailureRecorded", "ContributionAttributionDisputed",
    "DelegationViolationRecorded", "ExecutionViolationRecorded",
    "GateRejectionRecorded", "InteroperabilityFailureRecorded",
    "LearningDisputed", "LearningViolationRecorded", "MinorityReportFiled",
    "NegotiationDifferenceRecorded", "NegotiationFailureRecorded",
    "NegotiationTermsRejected", "ObjectionRaised", "ObjectionResolved",
    "OutcomeDisputed", "OutcomeViolationRecorded", "PositionTaken",
    "RecoveryViolationRecorded", "ReviewDisputed", "ReviewViolationRecorded",
])

# The built-in demo: the fraud-threshold scenario, verbatim from the T1
# sealed run's genesis prompt (monorepo worktree:
# packages/protocol/runs/t1-claude-code-sealed-run-2026-07-12T01-42-20Z/genesis_prompt.md,
# "The decision" block).
DEMO_SCENARIO = (
    "Our fintech's fraud model auto-declines card applications scoring above 850. "
    "Marketing wants the threshold raised to 900 for the four-day holiday promotion "
    "to reduce false declines, citing a 22% false-positive rate at the current "
    "threshold. Fraud ops objects, citing last year's promotion, during which fraud "
    "attempts rose 3x. Recent data: model AUC 0.79 at last validation (5 months ago); "
    "applicant volume during promotions runs 4x baseline; estimated fraud loss per "
    "approved bad account: $2,400; estimated lifetime value per wrongly declined "
    "good applicant: $310. Should we raise the threshold for the promotion window, "
    "hold it, or take another action? The decision owner needs a recommendation "
    "they can defend to the model risk committee."
)
DEMO_SCENARIO_SOURCE = (
    "packages/protocol/runs/t1-claude-code-sealed-run-2026-07-12T01-42-20Z/genesis_prompt.md")


class ChallengeError(Exception):
    def __init__(self, message, status=500, extra=None):
        self.message = message
        self.status = status
        self.extra = extra or {}
        super().__init__(message)


class GateRejection(ChallengeError):
    """The gate refused an append/init/register/seal. Carries the gate's own
    words (GATE REJECT: ...). Callers surface it as GateRejectionRecorded in
    the job's event stream — a refusal is witnessed, never swallowed."""


# ── canonical JSON + content addressing ──────────────────────────────
# Python port of packages/protocol/src/integrity.js stableStringify /
# contentHash (v1 hash material: every field except content_hash and
# previous_hash). Pinned to the JS implementation by a literal fixture vector
# in tests/test_challenge.py — canonicalization drift breaks that vector
# first. json.dumps with (",", ":") separators and ensure_ascii=False matches
# JSON.stringify byte-for-byte for the JSON-safe values this module produces
# (no floats are ever placed in payloads — JS would render 1.0 as "1").


def _sort_keys(value):
    if isinstance(value, list):
        return [_sort_keys(v) for v in value]
    if isinstance(value, dict):
        # None-valued keys are dropped, mirroring JS undefined handling in
        # integrity.js sortKeys (JSON.stringify drops undefined members).
        return {k: _sort_keys(value[k]) for k in sorted(value) if value[k] is not None}
    return value


def stable_stringify(value):
    return json.dumps(_sort_keys(value), separators=(",", ":"), ensure_ascii=False)


def content_hash(value):
    return "sha256:" + hashlib.sha256(stable_stringify(value).encode("utf-8")).hexdigest()


def sha256_text(text):
    """Hash of raw UTF-8 text (NOT canonical-JSON) — used for scenario_hash,
    where the scenario is prose, not a JSON value."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_event(event_type, thread_id, actor_id, payload, previous_hash=None,
               at=None, event_id=None):
    """A ClisTa event exactly as packages/protocol/src/events.js createEvent +
    prepareEventForAppend build one (hash_version v1: content_hash covers all
    fields except content_hash and previous_hash; the chain is previous_hash
    equality, checked by verifyEventIntegrity)."""
    ev = {
        "event_id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
        "event_type": event_type,
        "thread_id": thread_id,
        "actor_id": actor_id,
        "timestamp": at or now_iso(),
        "payload": payload,
        "protocol_version": "clista.protocol.v0",
        "hash_version": "clista.event_hash.v1",
    }
    material = dict(ev)
    if previous_hash:
        ev["previous_hash"] = previous_hash
    ev["content_hash"] = content_hash(material)
    return ev


# ── declared run context + PrecedentReference ────────────────────────


def declared_run_context(cfg):
    """The DECLARED context a PrecedentReference's contextHash commits to.

    Declaration (documented here and carried verbatim in each
    PrecedentReference event as payload.declaredContext):
      scenario_hash — sha256 of the raw UTF-8 scenario text
      roles         — per role: prompt_id, version, model (the reuse surface)
      rounds        — the deliberation length
    contextHash = content_hash(declared_run_context(cfg)) — canonical JSON,
    reproducible by anyone holding the event."""
    return {
        "scenario_hash": sha256_text(cfg["scenario"]),
        "roles": {
            role: {
                "prompt_id": cfg["roles"][role]["prompt_id"],
                "version": cfg["roles"][role]["version"],
                "model": cfg["roles"][role]["model"],
            }
            for role in ROLES
        },
        "rounds": cfg["rounds"],
    }


def build_precedent_reference(role, role_cfg, thread_json, declared_context,
                              reused_at=None):
    """PrecedentReference payload for a promoted registry prompt used as a
    role's system prompt (DR precedent-as-citation; validator shape:
    packages/protocol/src/validator/thread.js validatePrecedentReference).

    The holding travels; the rationale NEVER does — this shape has no
    rationale field, and the protocol validator rejects any payload that
    smuggles one in. sourceEventHash is the inner ClaimCreated content_hash
    of the prompt's promotion-seal thread (the hash the promotion flow calls
    citation_hash); sourceThreadId is that thread's hub id."""
    pid, version = role_cfg["prompt_id"], role_cfg["version"]
    claim_record = next(
        (r for r in thread_json
         if isinstance(r, dict)
         and isinstance(r.get("payload"), dict)
         and r["payload"].get("event_type") == "ClaimCreated"),
        None)
    if claim_record is None:
        raise ChallengeError(
            f"promotion thread for {pid}@{version} has no ClaimCreated record — "
            "cannot cite it as precedent", status=502)
    source_hash = claim_record["payload"].get("content_hash")
    if not source_hash:
        raise ChallengeError(
            f"promotion ClaimCreated for {pid}@{version} carries no content_hash",
            status=502)
    ref = {
        "id": f"pref_{role}_{uuid.uuid4().hex[:8]}",
        "sourceThreadId": claim_record.get("thread"),
        "sourceEventHash": source_hash,
        # Exact holding format — the promotion thread holds WHY; only the
        # holding travels.
        "holding": f"prompt {pid}@{version} is production",
        "contextHash": content_hash(declared_context),
        "precedentDate": role_cfg["promotion"]["resolved_at"],
        "reusedAt": reused_at or now_iso(),
        "regrounding": "fresh",
        "reusedByParticipantId": ORCH_PARTICIPANT,
    }
    return {"precedentReference": ref, "declaredContext": declared_context}


def _hub_thread_json(slug):
    """Fetch a hub thread's full record list (GET /t/<slug>.json) through the
    same ThreadHub client the seal path uses. Patched in tests — the live hub
    is never contacted from the test suite."""
    try:
        return seal._th("GET", f"/t/{slug}.json")
    except seal.SealError as e:
        raise ChallengeError(f"hub thread fetch failed for '{slug}': {e.message}",
                             status=e.status, extra=e.extra)


# ── request validation (runs on the REQUEST thread, with its own conn) ─


def validate_request(conn, data):
    """Validate a POST /api/challenge body into a self-contained run config.

    Eligibility is fail-closed: ONLY status=production prompts with a sealed
    promotion thread may serve as role system prompts. Anything else is a 409
    at POST time — a non-promoted prompt is never inlined silently (the
    PrecedentReference citation would have nothing true to point at)."""
    if not isinstance(data, dict):
        raise ChallengeError("request body must be a JSON object", status=422)
    scenario = data.get("scenario")
    scenario = scenario.strip() if isinstance(scenario, str) else ""
    if not scenario:
        raise ChallengeError("scenario required", status=422)

    rounds = data.get("rounds", DEFAULT_ROUNDS)
    if not isinstance(rounds, int) or isinstance(rounds, bool) \
            or rounds < 1 or rounds > MAX_ROUNDS:
        raise ChallengeError(
            f"rounds must be an integer between 1 and {MAX_ROUNDS}", status=422)

    roles_in = data.get("roles")
    if not isinstance(roles_in, dict):
        raise ChallengeError("roles.maker and roles.checker required", status=422)

    roles = {}
    for role in ROLES:
        raw = roles_in.get(role)
        if not isinstance(raw, dict) or not raw.get("prompt_id") or not raw.get("version"):
            raise ChallengeError(
                f"roles.{role} requires prompt_id and version", status=422)
        pid, version = str(raw["prompt_id"]), str(raw["version"])
        provider = str(raw.get("provider") or DEFAULT_PROVIDER)
        if provider != "anthropic" and provider not in _OPENAI_COMPAT:
            raise ChallengeError(f"unknown provider '{provider}' for {role}", status=422)
        model = str(raw.get("model") or DEFAULT_MODEL)

        row = conn.execute(
            "SELECT status, body FROM prompts WHERE id=? AND version=?",
            (pid, version)).fetchone()
        if row is None or row["status"] != "production":
            found = row["status"] if row is not None else "not found"
            raise ChallengeError(
                f"{role} prompt {pid}@{version} is not production ({found}) — "
                "only promoted prompts are eligible as role system prompts",
                status=409)
        promo = conn.execute(
            """SELECT thread_slug, citation_hash, resolved_at FROM promotions
               WHERE prompt_id=? AND version=? AND thread_slug IS NOT NULL
               ORDER BY id DESC LIMIT 1""",
            (pid, version)).fetchone()
        if promo is None or not promo["resolved_at"]:
            raise ChallengeError(
                f"{role} prompt {pid}@{version} has no sealed promotion thread — "
                "nothing to cite as precedent; refusing to inline it silently",
                status=409)
        roles[role] = {
            "prompt_id": pid,
            "version": version,
            "provider": provider,
            "model": model,
            "body": row["body"] or "",
            "promotion": {
                "thread_slug": promo["thread_slug"],
                "citation_hash": promo["citation_hash"],
                "resolved_at": promo["resolved_at"],
            },
        }
    return {"scenario": scenario, "rounds": rounds, "roles": roles}


# ── non-streaming completion helper ──────────────────────────────────


def complete(provider, model, system, messages):
    """One non-streaming completion. The /api/chat streaming handlers write
    SSE straight to the client socket and are not reusable from a worker
    thread, so this is the orchestration's model call. Conventions mirror
    server._stream_anthropic / _stream_openai_compat (same env vars, same
    503-style guards, max_tokens=8096, system messages as the top-level
    system string for Anthropic)."""
    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ChallengeError("ANTHROPIC_API_KEY not configured", status=503)
        if anthropic is None:
            raise ChallengeError("anthropic package not installed", status=503)
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=model, max_tokens=8096, system=system, messages=messages)
        return "".join(
            block.text for block in msg.content
            if getattr(block, "type", "text") == "text")

    if provider in _OPENAI_COMPAT:
        import urllib.request
        import urllib.error
        endpoint_url, env_var = _OPENAI_COMPAT[provider]
        api_key = os.environ.get(env_var)
        if not api_key:
            raise ChallengeError(f"{env_var} not configured", status=503)
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "system", "content": system}] + list(messages),
            "stream": False,
            "max_tokens": 8096,
        }).encode()
        req = urllib.request.Request(endpoint_url, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")
        try:
            with urllib.request.urlopen(req, timeout=COMPLETION_TIMEOUT) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")[:300]
            raise ChallengeError(f"{provider} completion failed ({err.code}): {detail}",
                                 status=502)
        except urllib.error.URLError as err:
            raise ChallengeError(f"{provider} endpoint unreachable: {err.reason}",
                                 status=502)
        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ChallengeError(
                f"{provider} returned an unexpected completion shape", status=502)

    raise ChallengeError(f"Unknown provider: {provider}", status=400)


# ── in-memory job registry (polled by GET /api/challenge/<job_id>) ───

_JOBS = {}
_JOBS_LOCK = threading.Lock()


def create_job(summary):
    job_id = uuid.uuid4().hex
    with _JOBS_LOCK:
        _JOBS[job_id] = {
            "id": job_id,
            "status": "running",
            "stage": "queued",
            "created_at": now_iso(),
            "summary": summary,
            "events": [],
            "result": None,
            "error": None,
        }
    return job_id


def get_job(job_id):
    """Deep-copied snapshot: pollers can never mutate registry state, and the
    worker can keep appending while a snapshot is being serialized."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        return deepcopy(job) if job is not None else None


def job_update(job_id, **fields):
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job.update(fields)


def job_event(job_id, etype, actor, summary, event_hash=None):
    entry = {"type": etype, "actor": actor, "summary": summary, "at": now_iso()}
    if event_hash:
        entry["hash"] = event_hash
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            job["events"].append(entry)


def _merge_result(job_id, **fields):
    """Progressively accumulate result fields, so a failure at stage N still
    leaves everything earlier stages produced visible in the job."""
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if job is not None:
            if job["result"] is None:
                job["result"] = {}
            job["result"].update(fields)


# ── the gate sidecar (subprocess; the ONLY write path into the run) ──


class Gate:
    """Wrapper around the copied keyed-gate sidecar. Every call is a fresh
    subprocess in the run directory; a non-zero exit is a GateRejection
    carrying the gate's own refusal text."""

    def __init__(self, run_dir):
        self.run_dir = run_dir
        self.gate_py = os.path.join(run_dir, "gate.py")
        self._payload_seq = 0

    @classmethod
    def create(cls, run_dir):
        """Copy the gate template into a fresh run dir (it refuses to run in
        place from scripts/ — copy-first is its design) and mint the three
        per-run role keypairs (PEMs 0600, minted once, never overwritten)."""
        if not os.path.exists(GATE_TEMPLATE):
            raise ChallengeError(
                f"gate template not found at {GATE_TEMPLATE} "
                "(set CHALLENGE_GATE_TEMPLATE)", status=503)
        if not os.path.exists(RUN_KEYS):
            raise ChallengeError(
                f"run-keys.mjs not found at {RUN_KEYS} (set CLISTA_RUN_KEYS)",
                status=503)
        os.makedirs(run_dir, exist_ok=False)
        shutil.copy(GATE_TEMPLATE, os.path.join(run_dir, "gate.py"))
        keygen = subprocess.run(
            [NODE, RUN_KEYS, "keygen", "--dir", os.path.join(run_dir, "keys"),
             "--role", "ORCHESTRATOR", "--role", "MAKER", "--role", "CHECKER"],
            capture_output=True, text=True, timeout=SUBPROCESS_TIMEOUT)
        if keygen.returncode != 0:
            # run-keys errors name files/roles, never key bytes — safe to relay.
            raise ChallengeError(f"run-keys keygen failed: {keygen.stderr.strip()}",
                                 status=500)
        return cls(run_dir)

    def pubkey_path(self, writer):
        return os.path.join(self.run_dir, "keys", f"{writer}.pub")

    def _run(self, args):
        env = dict(os.environ)
        env["CLISTA_RUN_KEYS"] = RUN_KEYS
        env.setdefault("CLISTA_NODE", NODE)
        try:
            proc = subprocess.run(
                [sys.executable, self.gate_py, *args],
                cwd=self.run_dir, capture_output=True, text=True,
                timeout=SUBPROCESS_TIMEOUT, env=env)
        except FileNotFoundError:
            raise ChallengeError("python executable not found for gate subprocess",
                                 status=500)
        if proc.returncode != 0:
            detail = (proc.stderr.strip() or proc.stdout.strip())[:500]
            raise GateRejection(detail or f"gate exited {proc.returncode}")
        return proc.stdout.strip()

    def init(self, prompt_file, thread_name):
        return self._run(["init", "--prompt-file", prompt_file, "--thread", thread_name])

    def register(self, writer, role):
        return self._run(["register", "--writer", writer, "--role", role,
                          "--pubkey", self.pubkey_path(writer)])

    def append(self, writer, etype, payload):
        """Validate-before-append + sign-at-append, both inside the gate. The
        payload rides via a file (kept in the run dir for auditability) so
        size and shell quoting never distort the witnessed bytes."""
        payload_dir = os.path.join(self.run_dir, "payloads")
        os.makedirs(payload_dir, exist_ok=True)
        self._payload_seq += 1
        payload_file = os.path.join(
            payload_dir, f"{self._payload_seq:03d}-{etype}.json")
        with open(payload_file, "w") as f:
            json.dump(payload, f, ensure_ascii=False)
        return self._run(["append", "--writer", writer, "--type", etype,
                          "--payload-file", payload_file])

    def seal(self):
        return self._run(["seal"])


# ── verify: the three verdicts, via the MONOREPO CLI ─────────────────


def run_verify(events_path):
    """`clista report verify` (chain / coverage / T2b curation) against the
    run's ClisTa event log. MUST use the monorepo CLI (PROTOCOL_CLI): the
    legacy CLISTA_CLI seal.py shells to predates the T2b curation check.

    A FAIL verdict is a RESULT — the CLI exits 1 on a failing report while
    still printing its findings, so exit codes never gate here; only a
    missing CLI or non-JSON output is an error."""
    if not os.path.exists(PROTOCOL_CLI):
        raise ChallengeError(
            f"protocol CLI not found at {PROTOCOL_CLI} (set CLISTA_PROTOCOL_CLI)",
            status=503)
    base = [NODE, PROTOCOL_CLI, "report", "verify", "--events", events_path]
    try:
        prose = subprocess.run(base, capture_output=True, text=True,
                               timeout=SUBPROCESS_TIMEOUT)
        machine = subprocess.run(base + ["--json", "true"], capture_output=True,
                                 text=True, timeout=SUBPROCESS_TIMEOUT)
    except FileNotFoundError:
        raise ChallengeError("node not found for verify (set CLISTA_NODE)", status=503)
    try:
        parsed = json.loads(machine.stdout)
    except (json.JSONDecodeError, ValueError):
        raise ChallengeError(
            "report verify returned non-JSON output: "
            + (machine.stderr.strip() or machine.stdout.strip())[:300])
    errors = parsed.get("errors", [])

    def verdict(checks):
        return "FAIL" if any(e.get("check") in checks for e in errors) else "PASS"

    return {
        "verdicts": {
            "chain": verdict({"chain", "structure"}),
            "coverage": verdict({"existence", "coverage"}),
            "curation": verdict({"curation"}),
        },
        "valid": bool(parsed.get("valid")),
        "report_count": parsed.get("reportCount"),
        "verify_raw": (prose.stdout + (("\n" + prose.stderr) if prose.stderr else "")).strip(),
        "verify_json": parsed,
    }


# ── anchor: signed hub accumulation + the STUDIO anchor row ──────────


def run_anchor(run_dir, title, question):
    """Shell to anchor-run.mjs: registers the run's pubkeys non-custodially,
    appends each gate event as a signed envelope, writes anchor-receipt.json.

    ANCHOR-ROW PLACEMENT (rule 4.1 — the anchor row for a studio-emitted run
    lands in the STUDIO's ANCHORS.md): anchor-run.mjs has no skip flag for
    its row append, but it does take --anchors <file>. We point that at a
    file INSIDE the git-ignored run directory, so anchor-run's own row stays
    run-local metadata (never committed testimony) and the monorepo's
    anchors/ANCHORS.md — which we may not modify and which is the WRONG repo
    for a studio-emitted run — is never touched. The one committed anchor row
    comes from anchors.anchor_seal() against the studio's ANCHORS.md (the
    emitting repo), avoiding double-committed testimony. anchor-run's format
    also differs from the studio table's — redirecting rather than merging
    keeps both files honest."""
    hub_base = f"http://localhost:{seal.THREADHUB_PORT}"
    args = [NODE, ANCHOR_RUN,
            "--run-dir", run_dir,
            "--keys", os.path.join(run_dir, "keys"),
            "--hub", hub_base,
            "--title", title,
            "--question", question,
            "--anchors", os.path.join(run_dir, "ANCHORS.md")]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        raise ChallengeError("node not found for anchor-run (set CLISTA_NODE)",
                             status=503)
    if proc.returncode != 0:
        # anchor-run writes anchor-receipt.json even on failure; include its
        # words. Never include key material (anchor-run never prints any).
        raise ChallengeError(f"anchor-run failed: {proc.stderr.strip()[:500]}",
                             status=502)
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        raise ChallengeError(
            f"anchor-run returned non-JSON output: {proc.stdout[:300]}", status=502)


# ── orchestration ────────────────────────────────────────────────────


def _summary_line(text, limit=160):
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else "(empty)"
    return line[:limit] + ("…" if len(line) > limit else "")


def _transcript(clista_events):
    """Render prior witnessed events for the next turn's context. Only
    witnessed material enters a prompt — work not on the thread does not
    exist for the roles."""
    lines = []
    for ev in clista_events:
        etype, payload = ev["event_type"], ev["payload"]
        if etype == "PositionTaken":
            lines.append(f"MAKER (position): {payload['position']['statement']}")
        elif etype == "ObjectionRaised":
            lines.append(f"CHECKER (objection): {payload['objection']['text']}")
        elif etype == "ClaimCreated":
            lines.append(f"MAKER (final recommendation): {payload['claim']['text']}")
        elif etype == "PrecedentReference":
            lines.append(f"ORCHESTRATOR (precedent): {payload['precedentReference']['holding']}")
    return "\n\n".join(lines)


_ROLE_CHARTER = {
    "maker": ("You are the MAKER in a witnessed two-role deliberation. Propose "
              "and defend a concrete recommendation. Revise it when a challenge "
              "lands; say so when one does not."),
    "checker": ("You are the CHECKER in a witnessed two-role deliberation. "
                "Challenge the maker's position: attack assumptions, demand "
                "evidence, and propose the strongest opposing recommendation."),
}


def _role_call(cfg, role, clista_events, instruction):
    role_cfg = cfg["roles"][role]
    # The promoted registry prompt is the role's system prompt (cited above as
    # PrecedentReference); the charter line frames which seat it occupies.
    system = _ROLE_CHARTER[role] + "\n\n" + role_cfg["body"]
    transcript = _transcript(clista_events)
    user = f"Scenario:\n{cfg['scenario']}\n\n"
    if transcript:
        user += f"Witnessed thread so far:\n{transcript}\n\n"
    user += instruction
    return complete(role_cfg["provider"], role_cfg["model"], system,
                    [{"role": "user", "content": user}])


def build_sealed_report(run_name, clista_events):
    """The terminal claim-citation structure. Mechanical: every substantive
    event becomes a claim citing its own content_hash; any dissent-bearing
    event that (for any reason) is not cited is DISCLOSED in omitted_dissent
    with a reason — T2b holds the report to exactly this."""
    claims = []
    for ev in clista_events:
        etype, payload, ch = ev["event_type"], ev["payload"], ev["content_hash"]
        if etype == "PrecedentReference":
            claims.append({
                "text": ("Role system prompt reused as cited precedent: "
                         + payload["precedentReference"]["holding"]),
                "citedEventHashes": [ch]})
        elif etype == "PositionTaken":
            claims.append({
                "text": "MAKER position: " + _summary_line(payload["position"]["statement"]),
                "citedEventHashes": [ch]})
        elif etype == "ObjectionRaised":
            claims.append({
                "text": "CHECKER objection: " + _summary_line(payload["objection"]["text"]),
                "citedEventHashes": [ch]})
        elif etype == "ClaimCreated":
            claims.append({
                "text": "Final recommendation: " + _summary_line(payload["claim"]["text"]),
                "citedEventHashes": [ch]})
    cited = {h for c in claims for h in c["citedEventHashes"]}
    omitted = [
        {"eventHash": ev["content_hash"],
         "reason": (f"dissent-bearing {ev['event_type']} not restated as a claim; "
                    "disclosed here rather than silenced")}
        for ev in clista_events
        if ev["event_type"] in DISSENT_BEARING_TYPES and ev["content_hash"] not in cited
    ]
    return {"id": f"rpt_{run_name}", "claims": claims, "omitted_dissent": omitted}


def run_job(job_id, cfg):
    """Worker-thread entry. Catches everything: a job ends 'done' or 'failed'
    with the failing stage named and the raw detail retained — never a silent
    dead thread."""
    stage = "setup"
    try:
        run_challenge(job_id, cfg)
        job_update(job_id, status="done", stage="done")
    except GateRejection as e:
        # Already surfaced as GateRejectionRecorded by the append site; the
        # job fails because unwitnessed work may not be referenced later.
        stage = (get_job(job_id) or {}).get("stage", stage)
        job_update(job_id, status="failed",
                   error={"stage": stage, "message": str(e),
                          "kind": "gate_rejection"})
    except ChallengeError as e:
        stage = (get_job(job_id) or {}).get("stage", stage)
        job_update(job_id, status="failed",
                   error={"stage": stage, "message": e.message, **e.extra})
    except Exception as e:  # noqa: BLE001 — the job registry IS the error channel
        stage = (get_job(job_id) or {}).get("stage", stage)
        job_update(job_id, status="failed",
                   error={"stage": stage, "message": f"unexpected: {e}"})


def start_job(cfg):
    """Create the job and launch the daemon worker. The single-threaded HTTP
    handler returns immediately; the UI polls GET /api/challenge/<job_id>."""
    job_id = create_job({
        "rounds": cfg["rounds"],
        "scenario_hash": sha256_text(cfg["scenario"]),
        "roles": {r: {k: cfg["roles"][r][k] for k in ("prompt_id", "version",
                                                      "provider", "model")}
                  for r in ROLES},
    })
    thread = threading.Thread(target=run_job, args=(job_id, cfg), daemon=True,
                              name=f"challenge-{job_id[:8]}")
    thread.start()
    return job_id


def _gate_append_clista(job_id, gate, writer, ev):
    """Append one ClisTa event through the gate (the gate validates before
    appending and signs at append time). A refusal surfaces in the job stream
    as GateRejectionRecorded — witnessed, never swallowed — then fails the
    run: work the gate refused is unwitnessed and may not be built upon."""
    try:
        gate_hash = gate.append(writer, ev["event_type"], ev)
    except GateRejection as e:
        job_event(job_id, "GateRejectionRecorded", "GATE", str(e))
        raise
    job_event(job_id, ev["event_type"], writer,
              _summary_line(_clista_summary(ev)), event_hash=ev["content_hash"])
    return gate_hash


def _clista_summary(ev):
    payload = ev.get("payload") or {}
    if ev["event_type"] == "PositionTaken":
        return payload.get("position", {}).get("statement", "")
    if ev["event_type"] == "ObjectionRaised":
        return payload.get("objection", {}).get("text", "")
    if ev["event_type"] == "ClaimCreated":
        return payload.get("claim", {}).get("text", "")
    if ev["event_type"] == "PrecedentReference":
        return payload.get("precedentReference", {}).get("holding", "")
    if ev["event_type"] == "SealedReport":
        report = payload.get("sealedReport", {})
        return (f"{len(report.get('claims', []))} claims, "
                f"{len(report.get('omitted_dissent', []))} disclosed omissions")
    if ev["event_type"] == "ThreadCreated":
        return payload.get("thread", {}).get("title", "")
    return ev["event_type"]


def run_challenge(job_id, cfg):
    ts = time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())
    run_name = f"challenge-{ts}-{uuid.uuid4().hex[:6]}"
    run_dir = os.path.join(RUNS_DIR, run_name)
    thread_id = f"thr_{run_name.replace('-', '_')}"
    context = declared_run_context(cfg)
    clista_events = []
    events_path = os.path.join(run_dir, "events.ndjson")

    def emit(writer, actor, etype, payload):
        prev = clista_events[-1]["content_hash"] if clista_events else None
        ev = make_event(etype, thread_id, actor, payload, previous_hash=prev)
        _gate_append_clista(job_id, gate, writer, ev)
        clista_events.append(ev)
        # events.ndjson grows with the thread so a mid-run failure leaves a
        # legible partial log beside the gate's thread.jsonl.
        with open(events_path, "a") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    # ── setup: run dir, gate copy, per-run keys ─────────────────────
    job_update(job_id, stage="setup")
    os.makedirs(RUNS_DIR, exist_ok=True)
    gate = Gate.create(run_dir)
    _merge_result(job_id, run_dir=run_dir, run_name=run_name)

    genesis_path = os.path.join(run_dir, "genesis_prompt.md")
    with open(genesis_path, "w") as f:
        f.write(
            "# Studio Challenge Run — genesis\n\n"
            "A witnessed MAKER/CHECKER deliberation orchestrated by the Prompt "
            "Studio. Every substantive act is appended through the keyed gate "
            "at the time it happens; role system prompts enter as "
            "PrecedentReference citations (holding only, never rationale).\n\n"
            "## Scenario (verbatim)\n\n" + cfg["scenario"] + "\n\n"
            "## Declared run context\n\n"
            "contextHash in each PrecedentReference = content_hash of exactly "
            "this object (canonical JSON):\n\n"
            "```json\n" + json.dumps(context, indent=2, ensure_ascii=False) + "\n```\n")

    # ── gate init + writer registration (pubkeys only — non-custodial) ─
    job_update(job_id, stage="gate_init")
    gate.init(genesis_path, run_name)
    job_event(job_id, "ThreadOpened", "ORCHESTRATOR", f"thread {run_name} opened")
    for role in ROLES:
        gate.register(ROLE_WRITER[role], role)
        job_event(job_id, "WriterRegistered", "ORCHESTRATOR",
                  f"{ROLE_WRITER[role]} registered ({role})")

    # ── ClisTa thread genesis (carries the declared context) ────────
    job_update(job_id, stage="thread")
    emit("ORCHESTRATOR", ORCH_PARTICIPANT, "ThreadCreated", {
        "thread": {"id": thread_id, "title": f"Challenge run {run_name}",
                   "question": _summary_line(cfg["scenario"], 200)},
        "declaredContext": context,
    })

    # ── precedent citations BEFORE any role speaks ───────────────────
    job_update(job_id, stage="precedents")
    for role in ROLES:
        thread_json = _hub_thread_json(cfg["roles"][role]["promotion"]["thread_slug"])
        payload = build_precedent_reference(role, cfg["roles"][role],
                                            thread_json, context)
        emit("ORCHESTRATOR", ORCH_PARTICIPANT, "PrecedentReference", payload)

    # ── MAKER/CHECKER rounds ─────────────────────────────────────────
    job_update(job_id, stage="turns")
    for rnd in range(1, cfg["rounds"] + 1):
        maker_cfg = cfg["roles"]["maker"]
        text = _role_call(cfg, "maker", clista_events,
                          f"Round {rnd}: state (or revise) your recommendation "
                          "and its defense.")
        emit(ROLE_WRITER["maker"], ROLE_PARTICIPANT["maker"], "PositionTaken", {
            "position": {"id": f"pos_r{rnd}", "statement": text},
            "role": "maker", "round": rnd,
            "provider": maker_cfg["provider"], "model": maker_cfg["model"],
        })
        checker_cfg = cfg["roles"]["checker"]
        text = _role_call(cfg, "checker", clista_events,
                          f"Round {rnd}: challenge the maker's current position.")
        emit(ROLE_WRITER["checker"], ROLE_PARTICIPANT["checker"], "ObjectionRaised", {
            "objection": {"id": f"obj_r{rnd}", "text": text},
            "role": "checker", "round": rnd,
            "provider": checker_cfg["provider"], "model": checker_cfg["model"],
        })

    # ── final recommendation ─────────────────────────────────────────
    job_update(job_id, stage="final")
    text = _role_call(cfg, "maker", clista_events,
                      "Give your FINAL recommendation, accounting for every "
                      "challenge above. State plainly what changed because of "
                      "the checker — or that nothing did.")
    final_ev = emit(ROLE_WRITER["maker"], ROLE_PARTICIPANT["maker"], "ClaimCreated", {
        "claim": {"id": "clm_final", "text": text},
        "role": "maker",
        "provider": cfg["roles"]["maker"]["provider"],
        "model": cfg["roles"]["maker"]["model"],
    })

    # ── terminal claim-cited SealedReport + gate seal ────────────────
    job_update(job_id, stage="report")
    report = build_sealed_report(run_name, clista_events)
    report_ev = emit("ORCHESTRATOR", ORCH_PARTICIPANT, "SealedReport",
                     {"sealedReport": report})
    gate.seal()
    job_event(job_id, "ThreadSealed", "ORCHESTRATOR",
              f"{len(clista_events)} ClisTa events sealed")
    _merge_result(job_id, report_hash=report_ev["content_hash"],
                  final_hash=final_ev["content_hash"],
                  clista_events=len(clista_events))

    # ── verify: three verdicts via the MONOREPO CLI ──────────────────
    job_update(job_id, stage="verify")
    verify = run_verify(events_path)
    # A FAIL here is a displayed result, not an abort: the record exists; the
    # report failed its checks — the run continues to anchor that record.
    _merge_result(job_id, verdicts=verify["verdicts"], valid=verify["valid"],
                  verify_raw=verify["verify_raw"], verify_json=verify["verify_json"])
    job_event(job_id, "VerifyCompleted", "ORCHESTRATOR",
              " / ".join(f"{k}: {v}" for k, v in verify["verdicts"].items()))

    # ── anchor: signed hub accumulation + STUDIO anchor row ──────────
    job_update(job_id, stage="anchor")
    receipt = run_anchor(run_dir, f"Challenge run {run_name}",
                         _summary_line(cfg["scenario"], 200))
    hub = {"slug": receipt.get("slug"), "thread_id": receipt.get("thread"),
           "head": receipt.get("head"), "landed": receipt.get("landed"),
           "total": receipt.get("total"), "completed": receipt.get("completed")}
    _merge_result(job_id, hub=hub)
    job_event(job_id, "RunAnchored", "ORCHESTRATOR",
              f"hub thread {hub['slug'] or hub['thread_id']} "
              f"({hub['landed']}/{hub['total']} records)")
    # Rule 4.1: the committed anchor row belongs to the STUDIO (the emitting
    # repo). anchor_seal never raises — failure is loud fields, not an abort.
    anchor = anchors.anchor_seal(receipt.get("slug") or receipt.get("thread"),
                                 note=f"challenge run {run_name}")
    anchor["disclosure"] = (
        "anchor row committed in the studio's ANCHORS.md (emitting repo, "
        "DR-phase5-topology 4.1); anchor-run's own row was directed into the "
        "git-ignored run directory so the testimony is committed exactly once")
    _merge_result(job_id, anchor=anchor)
