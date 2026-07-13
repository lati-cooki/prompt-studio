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
/* Consensus Protocol Design System (0d24922c-…): warm paper, dissent rust,
   serif deliberation prose. Self-contained inline CSS — no external hosts,
   no static assets (the no-file-oracle property holds). System-font stack. */
:root{--paper-0:#FBFAF6;--paper-1:#F3F1EA;--paper-2:#EAE7DC;--ink-0:#17181B;--ink-1:#3B3D42;--ink-2:#6C6E74;--rule:#DDD9CE;--rule-strong:#C6C1B2;--dissent:#B23A1E;--dissent-ink:#8C2C13;--dissent-rule:#E3C3B3;--verify-wash:#E3EFE8;--verify-rule:#BAD6C6;--pending:#9A6B12;--font-serif:"IBM Plex Serif",ui-serif,Georgia,serif;--font-sans:"IBM Plex Sans",ui-sans-serif,system-ui,-apple-system,sans-serif;--font-mono:"IBM Plex Mono",ui-monospace,'SF Mono',Menlo,monospace}
*,*::before,*::after{box-sizing:border-box}
body{font:16px/1.55 var(--font-sans);max-width:46rem;margin:2.5rem auto;padding:0 1.25rem;color:var(--ink-1);background:var(--paper-0);-webkit-font-smoothing:antialiased}
.panel{background:var(--paper-1);border:1px solid var(--rule);border-radius:2px;padding:1.6rem 1.5rem}
.kicker{font:600 11px/1 var(--font-sans);letter-spacing:.08em;text-transform:uppercase;color:var(--dissent)}
h1{font-family:var(--font-serif);font-size:27px;font-weight:600;line-height:1.25;color:var(--ink-0);margin:.5rem 0 1rem}
p{margin:.6rem 0}
b{color:var(--ink-0)}
a{color:var(--dissent-ink);text-decoration:none;text-underline-offset:2px}
a:hover{color:var(--dissent);text-decoration:underline}
.lede{font-family:var(--font-serif);font-size:19px;font-weight:500;color:var(--ink-0);margin:1.4rem 0 .2rem}
label{display:block;font:600 13px/1.4 var(--font-sans);color:var(--ink-1);margin-top:1rem}
textarea,input{width:100%;box-sizing:border-box;font:15px/1.5 var(--font-serif);padding:.55rem;margin:.3rem 0 .2rem;background:var(--paper-0);border:1px solid var(--rule-strong);border-radius:2px;color:var(--ink-0)}
textarea{min-height:8rem;resize:vertical}
textarea:focus,input:focus{outline:none;box-shadow:0 0 0 3px rgba(178,58,30,.20);border-color:var(--dissent-rule)}
button{font:600 15px/1 var(--font-sans);padding:.7rem 1.3rem;margin-top:1.1rem;background:var(--dissent);color:#fff;border:1px solid var(--dissent);border-radius:3px;cursor:pointer}
button:hover{background:var(--dissent-ink)}
code{font-family:var(--font-mono);font-size:13px;background:var(--paper-2);border-radius:2px;padding:0 .25rem;color:var(--ink-1)}
#countdown{font-family:var(--font-mono);font-size:14px;color:var(--pending);font-weight:500}
#receipt{white-space:pre-wrap;font-family:var(--font-mono);font-size:13px;background:var(--verify-wash);border:1px solid var(--verify-rule);border-radius:2px;padding:1rem;display:none;color:var(--ink-1);margin-top:1rem}
small{display:block;color:var(--ink-2);font-size:12px;margin-top:1rem;line-height:1.5}
</style></head><body>
<main class="panel">
<div class="kicker">Objection window open</div>
<h1>File an objection</h1>
<p>Promotion under final comment: <b>${pidV}</b></p>
${greeting}
<p>Window closes at <code>${closes}</code> — <span id="countdown">…</span></p>
${evidenceHtml}${deliberationHtml}
<p class="lede">Find what the checker missed.</p>
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
</main>
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
