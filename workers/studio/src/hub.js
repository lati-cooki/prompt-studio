// hub.js — the studio Worker's ONLY channel to the hub: thin wrappers over
// the HUB service binding. The binding is the capability — no secret
// crosses this boundary, and hub invariants stay behind hub code.
//
// ── HubInternal CONTRACT (the entrypoint itself lands hub-side in a later
//    task; tests bind test/hub-stub.js to the same shape) ────────────────
//
// A named WorkerEntrypoint exported by the threadhub-cf Worker as
// `HubInternal`, bound here via wrangler services:
//   { "binding": "HUB", "service": "threadhub-cf", "entrypoint": "HubInternal" }
//
//   mintIdentity({ display_name, kind }) -> { id }
//     Mints one custodial hub identity (the hub holds the keys — DR 5.5)
//     and returns its id. display_name and kind are the ONLY fields that
//     ever cross — an objector's contact string must never appear in any
//     argument (DR 5.6 privacy: contact stays in DO storage). Throws on
//     any hub-side failure; callers MUST treat a throw as "nothing was
//     filed" (mint-first ordering — the hub mint precedes every local
//     write, so a hub failure leaves no local state).
//
//   isPublished(slug) -> boolean
//     The thread's EFFECTIVE publication state (the last publication event
//     on the thread governs — hub-side pure function, the same rules the
//     Python effective_publication mirror implemented; this binding
//     retires that mirror on the Worker side). Callers treat a throw as
//     "not published": fail closed, render NOTHING.
//
// Until the services binding is uncommented in wrangler.jsonc, env.HUB is
// absent in production: mintIdentity throws (filing answers 502, nothing
// written) and isPublishedSafe returns false (no deliberation links) —
// both fail closed by construction.

/** Mint a custodial objector identity on the hub. Returns { id }. Throws
 * on any failure — including a malformed hub response — so the caller's
 * mint-first ordering holds: a throw here means nothing was filed. */
export async function mintIdentity(env, { display_name, kind }) {
  const res = await env.HUB.mintIdentity({ display_name, kind });
  const id = res && res.id;
  if (typeof id !== 'string' || id === '') {
    throw new Error('hub mintIdentity returned no id');
  }
  return { id };
}

/** Effective publication state, fail-closed: false on any error (hub
 * unreachable, binding absent, entrypoint missing). An unpublished or
 * unknowable association must render NOTHING — no dead links, no slug
 * leakage (DR-2026-07-13 rule 5: slugs are names, not credentials). */
export async function isPublishedSafe(env, slug) {
  try {
    return (await env.HUB.isPublished(slug)) === true;
  } catch {
    return false;
  }
}
