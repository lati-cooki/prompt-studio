export const EXTRACTION_PROMPT = `You read a decision-making conversation and extract its accountable structure.
Output ONLY a JSON object (no prose, no markdown fences) with these keys:
- "question": the decision question (string)
- "decision": the decision reached — the yes/no plus its statement (string)
- "evidence": array of {"source": string, "finding": string}
- "objections": array of {"text": string} — concerns raised that were NOT resolved
If something is absent from the conversation, use an empty string or empty array. Do not invent facts.`;

export function buildExtractionMessages(transcript) {
  const rendered = (Array.isArray(transcript) ? transcript : [])
    .map((m) => `${m && m.role ? m.role : 'user'}: ${m && typeof m.content === 'string' ? m.content : ''}`)
    .join('\n\n');
  return [
    { role: 'system', content: EXTRACTION_PROMPT },
    { role: 'user', content: `Conversation:\n\n${rendered}\n\nReturn the JSON object.` },
  ];
}
