export const EXTRACTION_PROMPT = `You read a decision-making conversation and extract its accountable structure.
Output ONLY a JSON object (no prose, no markdown fences) with these keys:
- "question": the decision question (string)
- "decision": the decision reached — the yes/no plus its statement (string)
- "evidence": array of {"source": string, "finding": string}
- "objections": array of {"text": string} — concerns raised that were NOT resolved
If something is absent from the conversation, use an empty string or empty array. Do not invent facts.`;

function _str(v) {
  return typeof v === 'string' ? v.trim() : '';
}

function _coerce(obj) {
  const evidence = Array.isArray(obj.evidence)
    ? obj.evidence
        .filter((e) => e && typeof e === 'object')
        .map((e) => ({ source: _str(e.source), finding: _str(e.finding) }))
        .filter((e) => e.source || e.finding)
    : [];
  const objections = Array.isArray(obj.objections)
    ? obj.objections
        .map((o) => (o && typeof o === 'object' ? _str(o.text) : _str(o)))
        .filter(Boolean)
        .map((text) => ({ text }))
    : [];
  return { question: _str(obj.question), decision: _str(obj.decision), evidence, objections };
}

const _EXPECTED_KEYS = ['question', 'decision', 'evidence', 'objections'];

export function parseExtraction(text) {
  if (typeof text !== 'string') throw new Error('no response text');
  let best = null;
  let searchFrom = 0;
  for (;;) {
    const start = text.indexOf('{', searchFrom);
    if (start === -1) break;
    let depth = 0, inStr = false, esc = false, end = -1;
    for (let i = start; i < text.length; i++) {
      const c = text[i];
      if (inStr) {
        if (esc) esc = false;
        else if (c === '\\') esc = true;
        else if (c === '"') inStr = false;
      } else if (c === '"') {
        inStr = true;
      } else if (c === '{') {
        depth++;
      } else if (c === '}') {
        depth--;
        if (depth === 0) { end = i; break; }
      }
    }
    if (end === -1) break;
    let obj = null;
    try { obj = JSON.parse(text.slice(start, end + 1)); } catch (e) { obj = null; }
    if (obj && typeof obj === 'object' && _EXPECTED_KEYS.some((k) => k in obj)) {
      best = obj;
    }
    searchFrom = end + 1;
  }
  if (!best) throw new Error('no extractable JSON object in response');
  return _coerce(best);
}

export function buildExtractionMessages(transcript) {
  const rendered = (Array.isArray(transcript) ? transcript : [])
    .map((m) => `${m && m.role ? m.role : 'user'}: ${m && typeof m.content === 'string' ? m.content : ''}`)
    .join('\n\n');
  return [
    { role: 'system', content: EXTRACTION_PROMPT },
    { role: 'user', content: `Conversation:\n\n${rendered}\n\nReturn the JSON object.` },
  ];
}
