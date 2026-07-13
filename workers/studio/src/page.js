// page.js — render_object_page ported from objections.py:744-845.
// Standalone server-rendered page, no studio shell, no JS dependencies
// beyond the countdown and the fetch that files the objection.

/** Python html.escape parity (objections.py:744-745 _e). Order matters
 * (& first), and the single quote is &#x27; — NOT &#39; — exactly what
 * html.escape(quote=True) emits. */
export function e(v) {
  return String(v)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#x27;');
}

/** objections.py:748-750 _js: JSON-encode for inline <script> embedding;
 * make it </script>-proof. (Python json.dumps additionally ASCII-escapes
 * non-ASCII; the values embedded here — urlsafe tokens and UTC timestamps
 * — are ASCII, so the bytes agree.) */
export function js(v) {
  return JSON.stringify(v).replace(/</g, '\\u003c').replace(/>/g, '\\u003e');
}

/** The outside skeptic's page: prompt id/version, window countdown,
 * pinned-evidence hash or its disclosed absence, textarea + contact.
 * EVERYTHING user-derived is escaped (e for HTML, js for the inline
 * script).
 *
 * deliberationUrl (Task 15): the doorstep link, precomputed by the caller
 * (DO deliberationLink → hub isPublishedSafe) — rendered only when
 * non-null, i.e. only when the cited deliberation thread is associated AND
 * effectively published. Null renders nothing at all (byte-identical to an
 * unassociated promotion's page). */
export function renderObjectPage(promotion, token, raw, deliberationUrl = null) {
  const ev = promotion.evidence;
  let evidenceHtml;
  if (ev !== null && typeof ev === 'object' && !Array.isArray(ev)) {
    evidenceHtml =
      '<p>Pinned evidence content_hash: ' +
      `<code>${e(ev.content_hash ?? 'unknown')}</code> ` +
      `(source: <code>${e(ev.source_file ?? 'unknown')}</code>)</p>`;
  } else {
    evidenceHtml =
      '<p>No pinned eval evidence is attached to this promotion — it ' +
      'proceeded with that absence disclosed.</p>';
  }
  let greeting = '';
  if (token.invitee_label) {
    greeting = `<p>Invitation for: <b>${e(token.invitee_label)}</b></p>`;
  }
  let deliberationHtml = '';
  if (deliberationUrl) {
    deliberationHtml =
      `<p><a href="${e(deliberationUrl)}">Read the deliberation ` +
      'this decision cites</a> — the sealed record, verifiable in ' +
      'place.</p>';
  }
  const pidV = `${e(promotion.prompt_id)} ${e(promotion.version)}`;
  const closes = e(promotion.closes_at);
  return `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Objection — ${pidV}</title>
<style>
body{font:16px/1.5 system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;color:#222}
textarea,input{width:100%;box-sizing:border-box;font:inherit;padding:.4rem;margin:.2rem 0 .8rem}
textarea{min-height:8rem}
button{font:inherit;padding:.5rem 1.2rem}
code{background:#f4f4f4;padding:0 .2rem}
#receipt{white-space:pre-wrap;background:#f4f4f4;padding:1rem;display:none}
small{color:#555}
</style></head><body>
<h1>File an objection</h1>
<p>Promotion under final comment: <b>${pidV}</b></p>
${greeting}
<p>Window closes at <code>${closes}</code> — <span id="countdown">…</span></p>
${evidenceHtml}${deliberationHtml}
<form id="f">
<label>Your objection<br><textarea name="body" required></textarea></label>
<label>Contact (stays with the studio operator; never published to the hub)<br>
<input name="contact" required></label>
<label>Display name (optional — how the public record names you)<br>
<input name="label"></label>
<button type="submit">File objection</button>
</form>
<p id="receipt"></p>
<small>Filing records your objection under a custodial hub identity; your
receipt will disclose custody and show you how to verify the sealed record
yourself.</small>
<script>
var closesAt = new Date(${js(promotion.closes_at)});
function tick() {
  var ms = closesAt - Date.now();
  document.getElementById("countdown").textContent =
    ms <= 0 ? "window elapsed" :
    Math.floor(ms/3600000) + "h " + Math.floor(ms/60000)%60 + "m " +
    Math.floor(ms/1000)%60 + "s remaining";
}
tick(); setInterval(tick, 1000);
document.getElementById("f").addEventListener("submit", function (ev) {
  ev.preventDefault();
  var f = ev.target;
  fetch("/api/object/" + ${js(raw)}, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({body: f.body.value, contact: f.contact.value,
                          label: f.label.value || undefined})
  }).then(function (r) { return r.json(); }).then(function (j) {
    var el = document.getElementById("receipt");
    el.style.display = "block";
    el.textContent = j.error ? ("Error: " + j.error)
      : ("Objection filed.\\nobjection_id: " + j.objection_id
         + "\\nbody_hash: " + j.body_hash
         + "\\nreceipt/status: " + j.status_url
         + "\\nKeep this URL — after the window seals it becomes your "
         + "verifiable receipt.");
  });
});
</script>
</body></html>`;
}
