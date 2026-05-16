// Friendly per-section copy + summary formatters for the live-analysis screen.
// Keys match AuditSectionName values emitted by the backend over SSE.

export const SECTION_PHASES = {
  maps: {
    section: 'maps',
    emoji: '🔍',
    label: 'Google Maps',
    runningCopy: 'Finding your business on Google Maps…',
    completedCopy: 'Found',
    summarize: (data) => {
      if (!data) return null;
      const { rating, review_count } = data;
      if (rating != null && review_count != null) {
        return `${rating} ★ (${formatNumber(review_count)} reviews)`;
      }
      return null;
    }
  },
  website: {
    section: 'website',
    emoji: '🌐',
    label: 'Website',
    runningCopy: 'Checking your website…',
    completedCopy: 'Loaded',
    summarize: (data) => {
      if (!data) return null;
      if (data.url) {
        try {
          return new URL(data.url).hostname.replace(/^www\./, '');
        } catch {
          return data.url;
        }
      }
      return null;
    }
  },
  instagram: {
    section: 'instagram',
    emoji: '📸',
    label: 'Instagram',
    runningCopy: 'Looking for your Instagram…',
    completedCopy: 'Found',
    summarize: (data) => {
      if (!data) return null;
      const parts = [];
      if (data.handle) parts.push(`@${data.handle}`);
      if (data.followers != null) parts.push(`${formatNumber(data.followers)} followers`);
      if (data.post_count != null) parts.push(`${data.post_count} posts`);
      return parts.length ? parts.join(' · ') : null;
    }
  },
  nap: {
    section: 'nap',
    emoji: '📋',
    label: 'NAP consistency',
    runningCopy: 'Cross-checking your name, address, and phone…',
    completedCopy: 'Done',
    summarize: () => null
  },
  competitors: {
    section: 'competitors',
    emoji: '📊',
    label: 'Nearby competitors',
    runningCopy: 'Comparing with nearby competitors…',
    completedCopy: 'Done',
    summarize: () => null
  }
};

export function defaultPhase(section) {
  return (
    SECTION_PHASES[section] ?? {
      section,
      emoji: '🔎',
      label: section,
      runningCopy: 'Working on it…',
      completedCopy: 'Done',
      summarize: () => null
    }
  );
}

// Friendly copy for the section_progress sub-step events the runner emits.
// Keep additions in line with whatever steps scrapers actually fire — an
// unknown step falls back to a generic "still working" line.
export function progressCopy(section, step, detail) {
  if (section === 'maps') {
    if (step === 'looking_up') return 'Searching Google Maps…';
    if (step === 'reading_listing') return 'Reading your listing…';
    if (step === 'found_listing') {
      if (detail?.rating != null && detail?.review_count != null) {
        return `Found you — ${detail.rating} ★ (${formatNumber(detail.review_count)} reviews)`;
      }
      return 'Found your listing.';
    }
    if (step === 'listing_not_found') return "Couldn't find your listing.";
  }
  if (section === 'website') {
    if (step === 'fetching') return 'Fetching your homepage…';
    if (step === 'parsing') return 'Reading the page…';
  }
  return null;
}

function formatNumber(n) {
  return new Intl.NumberFormat('en-IN').format(n);
}
