// constants.js — the byte-pinned refusal bodies and the receipt texts.
//
// BYTE-IDENTITY IS LOAD-BEARING (sealed architecture): the four generic
// bodies below are LITERAL constants copied character-for-character from
// objections.py. The JSON ones are PYTHON-serialized — server.py answers
// them via send_json → json.dumps with default separators (', ' / ': ')
// and default ensure_ascii=True, so there is a space after the colon and
// the em-dash rides as the six ASCII bytes backslash-u-2-0-1-4.
// JSON.stringify would drop the space and keep the em-dash literal —
// NEVER rebuild these at runtime; every refusal must serve these exact
// bytes.
//
// Provenance:
//   GENERIC_404_JSON  — objections.py:119 ({"error": "not found"}), bytes
//                       as serialized by server.py:411-415 send_json
//   GENERIC_404_HTML  — objections.py:120-122
//   GENERIC_429_JSON  — objections.py:127, bytes via send_json (the
//                       em-dash is ASCII-escaped under ensure_ascii)
//   GENERIC_429_HTML  — objections.py:128-130 (sent utf-8 raw — the
//                       em-dash stays a literal em-dash here)

export const GENERIC_404_JSON = '{"error": "not found"}';
export const GENERIC_404_HTML =
  "<!doctype html><meta charset='utf-8'><title>Not found</title>" +
  "<p>Not found.</p>";

export const GENERIC_429_JSON =
  '{"error": "rate limited \\u2014 try again shortly"}';
export const GENERIC_429_HTML =
  "<!doctype html><meta charset='utf-8'><title>Too many requests</title>" +
  "<p>Too many requests — try again shortly.</p>";

// Content-Type parity with the Python server: send_json sends
// 'application/json' with NO charset parameter; the HTML paths send
// 'text/html; charset=utf-8'. Both pinned by the byte-identity tests.
export const JSON_TYPE = 'application/json';
export const HTML_TYPE = 'text/html; charset=utf-8';

// ---------------------------------------------------------------------------
// DR 5.6 custody disclosure — travels ON the receipt (and the mint response,
// so the operator can forward it with the link), visible without querying
// the hub. Mint-time text is prospective (no objector identity exists yet);
// receipt-time text names the actual custodial identity.
// Verbatim from objections.py:169-177 and objections.py:180-193.

export const CUSTODY_DISCLOSURE_MINT =
  "Custody disclosure (DR-phase5-topology 5.6): objections filed through " +
  "this link are recorded under a CUSTODIAL identity minted for the " +
  "objector — the hub operator holds the signing keys, not the objector " +
  "(DR 5.5). Independence is therefore DOWNGRADED (DR 5.3): the sealed " +
  "record proves the studio recorded the objection and when — not that a " +
  "key only the objector controls signed it. Upgrade path: a " +
  "self-custodial identity (objector-held keys) is available on request " +
  "to the operator and replaces the custodial one for future objections.";

/** Receipt-time DR 5.6 disclosure naming the actual custodial identity.
 * Uses display_name + threadhub id only — never the internal
 * objector:<contact> writer name (the contact stays local). */
export function custodyDisclosureFor(writer) {
  return (
    "Custody disclosure (DR-phase5-topology 5.6): this objection is " +
    `recorded under the CUSTODIAL identity '${writer.display_name}' ` +
    `(hub identity ${writer.threadhub_id}) — the hub operator holds ` +
    "the signing keys, not you (DR 5.5). Independence is therefore " +
    "DOWNGRADED (DR 5.3): the record proves the studio recorded your " +
    "objection and when — not that a key only you control signed it. " +
    "Upgrade path: a self-custodial identity (keys you hold) is " +
    "available on request to the operator and replaces this custodial " +
    "one for future objections.");
}

// Verbatim from objections.py:623-637 (_receipt_instructions).
export function receiptInstructions(hub, slug, citationHash, recordHash) {
  return (
    "Verify this objection yourself, from any machine with Node:\n" +
    `  1. Save the checker:  curl -o verify.mjs ${hub}/verify.mjs\n` +
    `  2. Save the thread:   curl -o thread.json ${hub}/t/${slug}.json\n` +
    "  3. Run the checker:   node verify.mjs thread.json\n" +
    "It prints 'PASS: <n> records, head <hash>, signatures verified " +
    `k/n'. Compare that head to this receipt's citation_hash ` +
    `(${citationHash}) — they must match, and your objection is the ` +
    `record ${recordHash} inside that chain (${hub}/r/${recordHash}). ` +
    "A PASS proves chain integrity — your objection was recorded, " +
    "unaltered, in sequence, with how many records were signed " +
    "disclosed (signatures verified k/n). It proves recording, NOT " +
    "truth. Run it on your own machine against a saved copy: a verdict " +
    "produced by the hub's own host is not independent.");
}
