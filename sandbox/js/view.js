export const VIEWS = ['home', 'deliberate', 'decisions', 'registry', 'sessions'];

export function resolveView(raw) {
  const id = String(raw == null ? '' : raw).trim().replace(/^#/, '').toLowerCase();
  return VIEWS.includes(id) ? id : 'home';
}

export function homeState(sessionCount, decisionCount) {
  const s = Number(sessionCount) || 0;
  const d = Number(decisionCount) || 0;
  return s > 0 || d > 0 ? 'hub' : 'empty';
}

// Compact Decisions-header label for GET /api/promotions/metrics
// (Slice 5, DR-2026-07-12-fcp-metrics): counts, not ratios — "0/5" carries
// the denominator the ratio alone would hide. Returns null on malformed
// input so callers can degrade gracefully when the endpoint errors.
export function promotionMetricsLabel(m) {
  if (!m || typeof m !== 'object') return null;
  const total = m.terminal_total, waived = m.waived, invited = m.invited;
  if (![total, waived, invited].every(Number.isInteger)) return null;
  return `waive ${waived}/${total} · contested ${invited}/${total}`;
}
