"""Build Phase-2 decision-as-claim seal payloads for promotion outcomes.

Owner decision 2026-07-12: sealing stays on the validated decision-as-claim
sequence; formal DecisionRequested/Review/DecisionRecorded remains deferred.
FCP metadata rides inside the claim text as a trailing JSON object ("FCP: {...}")
so the sealed record carries the window facts without new event types.
"""
import json

HONESTY_BOUNDARY = (
    "Inputs and scores are pinned and hash-verifiable; LLM outputs are "
    "nondeterministic, so a re-run is fresh evidence, not a replay. The chain "
    "proves what was recorded and when — not that the prompt is good.")


def _fcp_meta(promotion):
    return {
        "opened_at": promotion["opened_at"],
        "closes_at": promotion["closes_at"],
        "resolved_at": promotion["resolved_at"],
        "state": promotion["state"],
        "window_hours": promotion["window_hours"],
        "fcp_waived": promotion["state"] == "waived",
        "waive_reason": promotion["waive_reason"],
        "objection_count": len(promotion["objections"]),
        "evidence_attached": promotion["evidence"] is not None,
    }


def _evidence_items(promotion):
    ev = promotion["evidence"]
    if not isinstance(ev, dict):
        return [{
            "source": "none",
            "finding": ("evidence_attached: false — promotion proceeded without a "
                        "pinned eval run; absence disclosed. " + HONESTY_BOUNDARY),
        }]
    return [{
        "source": f"eval:{ev.get('source_file', 'unknown')}",
        "finding": (f"Pinned eval run — model={ev.get('model')}, "
                    f"tokens={json.dumps(ev.get('tokens'))}, run_at={ev.get('run_at')}, "
                    f"content_hash={ev.get('content_hash', 'unknown')}. Re-run: {ev.get('rerun')}. "
                    + HONESTY_BOUNDARY),
    }]


def _objection_texts(promotion):
    out = []
    for o in promotion["objections"]:
        text = o["body"]
        if o.get("resolution"):
            text += f" [resolution: {o['resolution']} — {o.get('resolution_body', '')}]"
        out.append(text)
    return out


def build_seal_payload(promotion, outcome, decided_by):
    if outcome not in ("promoted", "aborted"):
        raise ValueError(f"invalid outcome: {outcome!r}")
    pid, ver = promotion["prompt_id"], promotion["version"]
    if outcome == "promoted":
        decision = f"{pid} {ver} promoted to production. FCP: "
    else:
        decision = f"{pid} {ver} NOT promoted (promotion aborted). FCP: "
    decision += json.dumps(_fcp_meta(promotion), sort_keys=True)
    return {
        "title": f"Promote {pid} v{ver} to production",
        "question": f"Should {pid} {ver} be promoted to production?",
        "decision": decision,
        "decidedBy": decided_by,
        "evidence": _evidence_items(promotion),
        "objections": _objection_texts(promotion),
    }


def build_demotion_payload(prompt_id, version, reason, decided_by, superseded_slug=None):
    ref = (f" Supersedes promotion record thread '{superseded_slug}'."
           if superseded_slug else " No prior promotion record found; absence disclosed.")
    return {
        "title": f"Deprecate {prompt_id} v{version}",
        "question": f"Should {prompt_id} {version} be deprecated?",
        "decision": f"{prompt_id} {version} deprecated: {reason}.{ref}",
        "decidedBy": decided_by,
        "evidence": [{"source": "registry",
                      "finding": f"status transition production->deprecated for {prompt_id}@{version}"}],
        "objections": [],
    }
