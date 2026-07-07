// Minimal markdown → HTML renderer for the structured recommendation body
// our backend produces. Handles only the patterns we generate:
//   - **bold** runs
//   - paragraphs separated by blank lines
//   - ordered lists with leading "1.", "2.", etc.
//
// We escape HTML before substituting **bold** so user content can't inject tags.

const ESCAPE = {
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
};

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (ch) => ESCAPE[ch]);
}

function renderInline(text) {
  // bold runs + `inline code` (recommendation bodies wrap handles and
  // snippets in backticks — these rendered as literal ` characters before)
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(
      /`([^`]+)`/g,
      '<code class="rounded bg-canvas-soft px-1 py-0.5 font-mono text-[0.85em]">$1</code>'
    );
}

export function renderMarkdown(src) {
  if (!src) return '';
  const blocks = String(src)
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .map((b) => b.trim())
    .filter(Boolean);

  const out = [];
  for (const block of blocks) {
    const lines = block.split('\n');
    const isOrderedList = lines.every((ln) => /^\s*\d+\.\s+/.test(ln));
    if (isOrderedList) {
      const items = lines
        .map((ln) => ln.replace(/^\s*\d+\.\s+/, ''))
        .map((ln) => `<li>${renderInline(ln)}</li>`)
        .join('');
      out.push(`<ol>${items}</ol>`);
      continue;
    }
    out.push(`<p>${renderInline(block.replace(/\n/g, ' '))}</p>`);
  }
  return out.join('');
}

// Pull the first **Why it matters** paragraph and the first ordered list from
// the structured body. Returns { why, howSteps[] } so the UI can show them
// in the dedicated WHY / HOW slots even without rendering full markdown.
export function splitRecommendationBody(src) {
  if (!src) return { why: '', howSteps: [] };
  const text = String(src).replace(/\r\n/g, '\n');

  const why = (() => {
    const re = /\*\*Why it matters\*\*\s*\n+([\s\S]+?)(?=\n{2,}\*\*|$)/i;
    const m = text.match(re);
    return m ? m[1].trim() : '';
  })();

  const howSteps = [];
  const howBlock = (() => {
    const re = /\*\*How to fix it\*\*\s*\n+([\s\S]+)$/i;
    const m = text.match(re);
    return m ? m[1].trim() : '';
  })();
  if (howBlock) {
    for (const ln of howBlock.split('\n')) {
      const m = ln.match(/^\s*\d+\.\s+(.+)$/);
      if (m) howSteps.push(m[1].trim());
    }
  }

  return { why, howSteps };
}
