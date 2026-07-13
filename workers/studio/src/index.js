// index.js — the studio Worker's front door. Everything here is transport;
// the state machine, validation, rendering and the refusal audit live in
// the single named StudioState DO. Hand-rolled routing, deliberately — the
// byte and header discipline below IS the requirement, and a framework's
// helpful defaults (charset suffixes, 405s, HEAD synthesis, error pages)
// are exactly the oracles this surface must not have.
//
// ORDER IS LOAD-BEARING (server.py _front_door, ported):
//   1. The skeptic surface matches FIRST and needs no credential:
//      GET /object/* and POST /api/object/* go to the DO, which runs the
//      rate limit BEFORE token validation (objections.py order).
//   2. Everything else computes the operator role — constant-time bearer
//      comparison over sha256 digests — BEFORE any request body is read:
//      no byte of an unauthorized body is ever buffered, and the check
//      happens before route matching so there is no route-existence
//      oracle. An unset STUDIO_OPERATOR_TOKEN fails CLOSED (no operator
//      surface at all): the local server's "no token = localhost posture"
//      would be catastrophic on a public Worker.
//   3. Operator requests are routed by the DO; an authenticated request to
//      an unknown path still answers the wall bytes (see do.js).
//   4. EVERYTHING else — no bearer, wrong bearer, truncated bearer,
//      unknown path, wrong verb, all alike — answers the byte-identical
//      generic 404 HTML. NO 401 anywhere: a 401 is a route-existence
//      oracle; the wall answers 404 (objections.py:100-116 posture,
//      hardened: the Python server 401s in its localhost posture — this
//      deployment never does).
import { GENERIC_404_HTML, HTML_TYPE, JSON_TYPE } from './constants.js';
import { MAX_BODY_BYTES } from './do.js';

export { StudioState } from './do.js';

const respond = ({ status, contentType, body }) =>
  new Response(body, { status, headers: { 'content-type': contentType } });

const wall404 = () =>
  respond({ status: 404, contentType: HTML_TYPE, body: GENERIC_404_HTML });

// server.py _skeptic_surface, verbatim: the ONLY surface served without a
// bearer. Static assets: NONE, deliberately — the objection page is fully
// self-contained (inline CSS + inline JS), so the public surface needs
// zero static files and leaves no file-existence oracle.
function skepticSurface(method, path) {
  if (method === 'GET') return path.startsWith('/object/');
  if (method === 'POST') return path.startsWith('/api/object/');
  return false;
}

// server.py operator_authorized, hardened for a public deployment: the
// Python version returns true when no token is configured (localhost
// posture); here an unset/empty secret means NO request is ever operator.
// Comparison is constant-time over sha256 digests (hashing first makes it
// length-independent too — a string compare would leak a prefix oracle).
async function operatorAuthorized(request, env) {
  const secret = env.STUDIO_OPERATOR_TOKEN;
  if (typeof secret !== 'string' || secret === '') return false; // fail closed
  const header = request.headers.get('authorization') ?? '';
  const supplied = header.startsWith('Bearer ') ? header.slice('Bearer '.length) : '';
  const enc = new TextEncoder();
  const [a, b] = await Promise.all([
    crypto.subtle.digest('SHA-256', enc.encode(supplied)),
    crypto.subtle.digest('SHA-256', enc.encode(secret)),
  ]);
  return crypto.subtle.timingSafeEqual(a, b);
}

// Body text for the routes that are allowed to read one. An over-ceiling
// body (server.py MAX_BODY_BYTES) becomes a flag, not a payload — the DO
// answers 413 with the same semantics as the Python server, and on the
// filing surface the refusal audit still gets its 'malformed' witness.
async function readBody(request) {
  const bodyText = await request.text();
  if (bodyText.length > MAX_BODY_BYTES) return { bodyTooLarge: true };
  return { bodyText };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    const method = request.method;
    try {
      // DO instance name bumped 'studio'->'studio-prod' at the
      // consensusprotocol.ai cutover for a fresh, clean DO (staging held smoke
      // artifacts; a SQLite DO can't be wiped in place).
      const stub = env.STUDIO.get(env.STUDIO.idFromName('studio-prod'));
      // (1) The public skeptic surface — the DO rate-limits BEFORE
      // validating anything, per-IP via CF-Connecting-IP (never a
      // client-settable header on Cloudflare).
      if (skepticSurface(method, path)) {
        const ip = request.headers.get('cf-connecting-ip') ?? '?';
        const bodyParts = method === 'POST' ? await readBody(request) : {};
        return respond(
          await stub.publicHandle({ method, path, ip, ...bodyParts }));
      }
      // (2) Role — computed once, here, before any body is read.
      if (await operatorAuthorized(request, env)) {
        // (3) The operator API. Unknown paths come back as the wall bytes.
        const bodyParts = method === 'POST' ? await readBody(request) : {};
        return respond(
          await stub.operatorHandle({ method, path, search: url.search, ...bodyParts }));
      }
      // (4) The wall. One body, one shape, for every failure mode.
      return wall404();
    } catch (err) {
      // Last resort — never a stack trace, never a framework error page.
      console.error('studio worker unhandled error', err);
      return respond({
        status: 500,
        contentType: JSON_TYPE,
        body: '{"error": "internal error"}',
      });
    }
  },
};
