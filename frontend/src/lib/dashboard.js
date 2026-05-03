// Friendly helpers for the dashboard view.

export function scoreLabel(score) {
  if (score == null) return '';
  if (score >= 85) return 'Looking great';
  if (score >= 75) return 'Looking good';
  if (score >= 65) return 'A few wins waiting';
  if (score >= 50) return 'Some attention needed';
  return 'Let’s give it some love';
}

export function scoreEncouragement(score) {
  if (score == null) return '';
  if (score >= 85) return 'You’re ahead of most of your neighbours. Keep the streak up.';
  if (score >= 75) return 'You’re in good shape. A couple of quick wins will push you to great.';
  if (score >= 65) return 'Solid base — pick a small fix this week and watch the score rise.';
  if (score >= 50) return 'There are a handful of things customers will notice. We’ll start with the easy ones.';
  return 'No judgment here — we’ll walk you through it one step at a time.';
}

// Map a score to a Tailwind colour family from our design system.
export function scoreTone(score) {
  if (score == null) return 'muted';
  if (score >= 75) return 'healthy';
  if (score >= 55) return 'attention';
  return 'action';
}

export function statusToTone(status) {
  switch (status) {
    case 'good':
      return 'healthy';
    case 'warn':
      return 'attention';
    case 'bad':
      return 'action';
    case 'info':
    default:
      return 'muted';
  }
}

export function statusGlyph(status) {
  switch (status) {
    case 'good':
      return '✓';
    case 'warn':
      return '!';
    case 'bad':
      return '×';
    case 'info':
    default:
      return '·';
  }
}

const SEVERITY_RANK = { high: 0, medium: 1, low: 2 };

export function severityRank(s) {
  return SEVERITY_RANK[s] ?? 99;
}

export function severityLabel(severity) {
  if (severity === 'high') return 'High impact';
  if (severity === 'medium') return 'Medium impact';
  if (severity === 'low') return 'Quick win';
  return 'Suggested';
}

export function severityTone(severity) {
  if (severity === 'high') return 'action';
  if (severity === 'medium') return 'attention';
  if (severity === 'low') return 'healthy';
  return 'muted';
}

export function impactLabel(impact) {
  if (!impact) return null;
  const lc = impact.toLowerCase();
  if (lc.includes('big')) return 'Big lift';
  if (lc.includes('medium')) return 'Solid lift';
  if (lc.includes('small')) return 'Small lift';
  return impact;
}

// Pull the top N open recommendations across all sections by severity.
export function topOpenRecommendations(sections, n = 3) {
  const all = [];
  for (const section of sections ?? []) {
    for (const rec of section.recommendations ?? []) {
      if (rec.fix_status !== 'open') continue;
      all.push({ ...rec, sectionLabel: section.label, sectionEmoji: section.emoji });
    }
  }
  all.sort((a, b) => severityRank(a.severity) - severityRank(b.severity) || a.id - b.id);
  return all.slice(0, n);
}

// Trend helpers — driven by the `trend` field on the audit/section payload.
// Backend computes the direction (with a 2-point threshold) so the frontend
// stays in sync with the rule.
export function trendArrow(trend) {
  if (trend === 'up') return '↗';
  if (trend === 'down') return '↘';
  if (trend === 'flat') return '→';
  return null;
}

export function trendTone(trend) {
  if (trend === 'up') return 'healthy';
  if (trend === 'down') return 'action';
  if (trend === 'flat') return 'muted';
  return 'muted';
}

export function trendLabel(current, previous, trend) {
  if (current == null || previous == null) return 'First check';
  if (trend === 'flat') return 'Holding steady';
  const delta = current - previous;
  if (delta > 0) return `Up ${delta} from last check`;
  if (delta < 0) return `Down ${Math.abs(delta)} from last check`;
  return '';
}

// Friendly relative timestamps without dragging in a date library.
export function formatRelativeTime(iso) {
  if (!iso) return '';
  const then = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - then.getTime();
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin} min ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr} hr ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay === 1) return 'yesterday';
  if (diffDay < 7) return `${diffDay} days ago`;
  return then.toLocaleDateString();
}
