/**
 * VantageNorth Compliance Intelligence Hub
 * Vanilla JS. Loads stories.json, renders filterable grid with search.
 */

// ─── CONFIG ─────────────────────────────────────────────────────────
const CATEGORIES = {
  oil: 'Oil',
  gas: 'Gas',
  lng: 'LNG',
  hydrogen: 'Hydrogen',
  pipeline: 'Pipeline',
  power_electricity: 'Power / Electricity',
  data_centers: 'Data Centers',
  regulatory: 'Regulatory',
  environmental: 'Environmental',
  emergency_response: 'Emergency Response',
  safety: 'Safety',
  llr_aro: 'LLR / ARO',
  land_management: 'Land Management',
  carbon_climate: 'Carbon / Climate',
  acquisitions_md: 'Major Acquisitions',
  tax_finance: 'Tax / Finance',
};

const JURISDICTIONS = ['Alberta', 'British Columbia', 'Saskatchewan', 'Federal'];
const JURISDICTION_ABBR = {
  'Alberta': 'AB',
  'British Columbia': 'BC',
  'Saskatchewan': 'SK',
  'Federal': 'CA',
};

// ─── STATE ──────────────────────────────────────────────────────────
let stories = [];
let activeFilters = {
  jurisdiction: 'all',
  category: 'all',
  recency: 'all',
  updates: false,
  search: '',
};

// ─── BOOT ───────────────────────────────────────────────────────────
// Local stories.json is the source of truth — refreshed on each GitHub Action
// build and auto-deployed by Netlify. slug-map.json maps story URLs to their
// per-story page slugs so card links point to indexable Hub pages.
const STORIES_LOCAL = 'stories.json';
const STORIES_REMOTE = 'https://raw.githubusercontent.com/garryjvisser/vnc-hub-data/main/stories.json';
const SLUG_MAP_LOCAL = 'slug-map.json';

let slugMap = {};

async function init() {
  try {
    // Prefer local (always current via build), fall back to GitHub raw if local missing
    let raw;
    try {
      const res = await fetch(STORIES_LOCAL + '?v=' + Date.now(), { cache: 'no-store' });
      if (!res.ok) throw new Error('Local fetch returned ' + res.status);
      raw = await res.json();
    } catch (localErr) {
      console.warn('[Hub] Local fetch failed, trying GitHub:', localErr.message);
      const res = await fetch(STORIES_REMOTE + '?v=' + Date.now(), { cache: 'no-store' });
      raw = await res.json();
    }
    // Slug map (built by .github/scripts/build_hub.py). If missing, cards fall back to external URLs.
    try {
      const smRes = await fetch(SLUG_MAP_LOCAL + '?v=' + Date.now(), { cache: 'no-store' });
      if (smRes.ok) slugMap = await smRes.json();
    } catch (smErr) {
      console.warn('[Hub] slug-map not available, cards will link to original sources:', smErr.message);
    }
    // Only show approved stories
    stories = raw.filter(s => s.approved === true);
    populateStats();
    buildChips();
    render();
    attachListeners();
  } catch (err) {
    document.getElementById('story-grid').innerHTML = `
      <div class="empty-state">
        <h3>Couldn't load stories</h3>
        <p>${err.message}</p>
      </div>`;
  }
}

// ─── HERO STATS ─────────────────────────────────────────────────────
function populateStats() {
  const total = stories.length;
  const ab = stories.filter(s => (s.jurisdiction || '').includes('Alberta')).length;
  const bc = stories.filter(s => (s.jurisdiction || '').includes('British Columbia')).length;
  const sk = stories.filter(s => (s.jurisdiction || '').includes('Saskatchewan')).length;
  const fed = stories.filter(s => (s.jurisdiction || '').includes('Federal')).length;
  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set('stat-total', total);
  set('stat-ab', ab);
  set('stat-bc', bc);
  set('stat-sk', sk);
  set('stat-fed', fed);
}

// ─── CHIPS ──────────────────────────────────────────────────────────
function buildChips() {
  // Jurisdiction chips
  const jurEl = document.getElementById('jurisdiction-chips');
  JURISDICTIONS.forEach(jur => {
    const count = stories.filter(s => (s.jurisdiction || '').includes(jur)).length;
    if (count === 0) return;
    const btn = document.createElement('button');
    btn.className = 'chip';
    btn.dataset.filter = 'jurisdiction';
    btn.dataset.value = jur;
    btn.innerHTML = `${jur} <span class="chip-count">${count}</span>`;
    jurEl.appendChild(btn);
  });

  // Category chips
  const catEl = document.getElementById('category-chips');
  Object.entries(CATEGORIES).forEach(([key, label]) => {
    const count = stories.filter(s => (s.categories || []).includes(key)).length;
    if (count === 0) return;
    const btn = document.createElement('button');
    btn.className = 'chip';
    btn.dataset.filter = 'category';
    btn.dataset.value = key;
    btn.innerHTML = `${label} <span class="chip-count">${count}</span>`;
    catEl.appendChild(btn);
  });
}

// ─── FILTERING & RENDER ────────────────────────────────────────────
function filterStories() {
  const term = activeFilters.search.toLowerCase().trim();
  const now = Date.now();
  const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
  return stories.filter(s => {
    // Jurisdiction filter
    if (activeFilters.jurisdiction !== 'all') {
      if (!(s.jurisdiction || '').includes(activeFilters.jurisdiction)) return false;
    }
    // Category filter
    if (activeFilters.category !== 'all') {
      if (!(s.categories || []).includes(activeFilters.category)) return false;
    }
    // Recency filter — "New this week" means events PUBLISHED in last 7 days
    // Falls back to added_at if published_at isn't set
    if (activeFilters.recency === 'week') {
      const pubTime = new Date(s.published_at || s.added_at || 0).getTime();
      if (!pubTime || (now - pubTime) > WEEK_MS) return false;
    }
    // Updates-only filter — groups all regulatory updates/amendments
    // Combined with jurisdiction: Alberta + Updates = all Alberta regs updated
    if (activeFilters.updates === true) {
      if (!s.is_update) return false;
    }
    // Search filter
    if (term) {
      const hay = `${s.title} ${s.excerpt} ${s.source} ${s.vn_commentary}`.toLowerCase();
      if (!hay.includes(term)) return false;
    }
    return true;
  }).sort((a, b) => {
    // Primary sort: published_at (most recent real-world event first)
    // Fall back to added_at, then score
    const aPub = new Date(a.published_at || a.added_at || 0).getTime();
    const bPub = new Date(b.published_at || b.added_at || 0).getTime();
    if (aPub !== bPub) return bPub - aPub;
    return (b.score || 0) - (a.score || 0);
  });
}

function render() {
  const filtered = filterStories();
  const grid = document.getElementById('story-grid');
  document.getElementById('results-count').textContent = filtered.length;

  if (filtered.length === 0) {
    grid.innerHTML = `
      <div class="empty-state">
        <h3>No stories match these filters.</h3>
        <p>Try broadening your filters or clearing the search.</p>
      </div>`;
    return;
  }

  grid.innerHTML = filtered.map(s => renderCard(s)).join('');
}

// Keep card commentary to a punchy hook — first sentence or two, hard cap ~140 chars.
// Full commentary lives on the per-story page.
function shortCommentary(text, maxLen = 140) {
  if (!text) return '';
  const clean = String(text).trim();
  // Split on sentence terminators keeping the sentences
  const sentences = clean.split(/(?<=[.!?])\s+/);
  let hook = '';
  for (const s of sentences) {
    const candidate = hook ? hook + ' ' + s : s;
    if (candidate.length > maxLen) {
      if (!hook) {
        // Single sentence exceeds the cap — hard truncate at word boundary
        const cut = clean.substring(0, maxLen);
        return cut.replace(/\s+\S*$/, '') + '…';
      }
      break;
    }
    hook = candidate;
  }
  // If we captured everything and it's short, return as-is (no ellipsis)
  if (hook.length >= clean.length) return hook;
  return hook + ' …';
}

function renderCard(s) {
  const jurPrimary = (JURISDICTIONS.find(j => (s.jurisdiction || '').includes(j)) || '');
  const abbr = JURISDICTION_ABBR[jurPrimary] || jurPrimary;
  const jurClass = jurPrimary === 'Federal' ? 'federal' : '';
  const tier = s.tier === 1 ? 'Regulator' : s.tier === 2 ? 'News' : s.tier === 3 ? 'Trade press' : 'Association';
  const date = formatDate(s.published_at);
  const tags = (s.categories || []).slice(0, 4)
    .map(c => `<span class="tag">${CATEGORIES[c] || c}</span>`).join('');
  const commentary = s.vn_commentary
    ? `<div class="vn-commentary"><strong>VantageNorth take</strong>${escapeHtml(shortCommentary(s.vn_commentary))}</div>`
    : '';
  const updateBadge = s.is_update ? `<span class="pill update">UPDATE</span>` : '';
  const updateCardClass = s.is_update ? ' card--update' : '';
  // Prefer per-story Hub page when a slug exists; fall back to original source URL.
  const slug = slugMap[s.url];
  const href = slug ? `/stories/${slug}` : s.url;
  const externalAttrs = slug ? '' : ' target="_blank" rel="noopener"';
  const linkLabel = slug ? 'Read the full article &amp; the full VN take' : 'Read full article';
  return `
    <article class="card${updateCardClass}">
      <div class="card-meta">
        ${abbr ? `<span class="pill jur ${jurClass}">${abbr}</span>` : ''}
        <span class="pill tier">${tier}</span>
        ${updateBadge}
        <span class="card-date">${date}</span>
      </div>
      <h3><a href="${href}"${externalAttrs} style="color:inherit; text-decoration:none;">${escapeHtml(s.title)}</a></h3>
      <div class="card-source">${escapeHtml(s.source)}</div>
      <p class="card-excerpt">${escapeHtml(s.excerpt)}</p>
      ${commentary}
      <div class="card-tags">${tags}</div>
      <a href="${href}"${externalAttrs} class="card-link">${linkLabel}</a>
    </article>`;
}

function formatDate(iso) {
  if (!iso) return '';
  // Handle YYYY-MM-DD plain
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ─── LISTENERS ──────────────────────────────────────────────────────
function attachListeners() {
  // Chip clicks (event delegation)
  document.querySelectorAll('.chips').forEach(container => {
    container.addEventListener('click', e => {
      const chip = e.target.closest('.chip');
      if (!chip) return;
      const filter = chip.dataset.filter;
      const value = chip.dataset.value;
      // Update active state on sibling chips
      container.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      activeFilters[filter] = value;
      render();
      updateHash();
    });
  });

  // Search
  const searchEl = document.getElementById('search');
  let searchTimer;
  searchEl.addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      activeFilters.search = e.target.value;
      render();
    }, 150);
  });

  // Recency pill toggle (New this week)
  const recencyBtn = document.getElementById('recency-toggle');
  if (recencyBtn) {
    recencyBtn.addEventListener('click', () => {
      const isOn = recencyBtn.getAttribute('aria-pressed') === 'true';
      const next = !isOn;
      recencyBtn.setAttribute('aria-pressed', next ? 'true' : 'false');
      activeFilters.recency = next ? 'week' : 'all';
      render();
    });
  }

  // Updates-only pill toggle (regulatory updates/amendments)
  const updatesBtn = document.getElementById('updates-toggle');
  if (updatesBtn) {
    updatesBtn.addEventListener('click', () => {
      const isOn = updatesBtn.getAttribute('aria-pressed') === 'true';
      const next = !isOn;
      updatesBtn.setAttribute('aria-pressed', next ? 'true' : 'false');
      activeFilters.updates = next;
      render();
      updateHash();
    });
  }

  // Clear filters
  document.getElementById('clear-filters').addEventListener('click', e => {
    e.preventDefault();
    activeFilters = { jurisdiction: 'all', category: 'all', recency: 'all', updates: false, search: '' };
    document.querySelectorAll('.chips').forEach(container => {
      container.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
      const allChip = container.querySelector('[data-value="all"]');
      if (allChip) allChip.classList.add('active');
    });
    if (recencyBtn) recencyBtn.setAttribute('aria-pressed', 'false');
    if (updatesBtn) updatesBtn.setAttribute('aria-pressed', 'false');
    searchEl.value = '';
    render();
    history.replaceState(null, '', location.pathname);
  });

  // Restore state from URL hash
  restoreFromHash();
}

function updateHash() {
  const parts = [];
  if (activeFilters.jurisdiction !== 'all') parts.push(`jurisdiction=${encodeURIComponent(activeFilters.jurisdiction)}`);
  if (activeFilters.category !== 'all') parts.push(`category=${activeFilters.category}`);
  if (activeFilters.updates) parts.push('updates=1');
  const hash = parts.length ? '#' + parts.join('&') : '';
  history.replaceState(null, '', location.pathname + hash);
}

function restoreFromHash() {
  const hash = location.hash.slice(1);
  if (!hash) return;
  const params = new URLSearchParams(hash);
  const jur = params.get('jurisdiction');
  const cat = params.get('category');
  const upd = params.get('updates');
  if (jur) {
    const chip = document.querySelector(`.chip[data-filter="jurisdiction"][data-value="${CSS.escape(jur)}"]`);
    if (chip) chip.click();
  }
  if (cat) {
    const chip = document.querySelector(`.chip[data-filter="category"][data-value="${CSS.escape(cat)}"]`);
    if (chip) chip.click();
  }
  if (upd === '1') {
    const btn = document.getElementById('updates-toggle');
    if (btn) btn.click();
  }
}

// ─── GO ─────────────────────────────────────────────────────────────
init();
