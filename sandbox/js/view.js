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
