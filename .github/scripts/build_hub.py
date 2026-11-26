#!/usr/bin/env python3
"""
Build per-story HTML pages for the VantageNorth Compliance Hub.

Reads stories.json from the repo root, generates one indexable HTML page per
approved story into site/stories/<slug>.html, and regenerates site/sitemap.xml
and site/slug-map.json.

Runs inside the hub-build GitHub Action whenever stories.json changes.
"""
from __future__ import annotations
import html as html_module
import json
import re
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STORIES_JSON = REPO_ROOT / "stories.json"
SITE_DIR = REPO_ROOT / "site"
STORIES_DIR = SITE_DIR / "stories"
SITEMAP_PATH = SITE_DIR / "sitemap.xml"
SLUG_MAP_PATH = SITE_DIR / "slug-map.json"
SITE_STORIES_JSON = SITE_DIR / "stories.json"

HUB_URL = "https://hub.vantagenorth.ca"

CATEGORIES = {
    "oil": "Oil", "gas": "Gas", "lng": "LNG", "hydrogen": "Hydrogen",
    "pipeline": "Pipeline", "power_electricity": "Power / Electricity",
    "data_centers": "Data Centers", "regulatory": "Regulatory",
    "environmental": "Environmental", "emergency_response": "Emergency Response",
    "safety": "Safety", "llr_aro": "LLR / ARO", "land_management": "Land Management",
    "carbon_climate": "Carbon / Climate", "acquisitions_md": "Major Acquisitions",
    "tax_finance": "Tax / Finance",
}

JURISDICTION_ABBR = {
    "Alberta": "AB", "British Columbia": "BC",
    "Saskatchewan": "SK", "Federal": "CA",
}


def esc(s) -> str:
    return html_module.escape(str(s) if s is not None else "")


def slugify(text: str, max_len: int = 100) -> str:
    """URL-safe slug from text. Max 100 chars, word-boundary trim."""
    s = (text or "").lower()
    # Remove common punctuation but keep word chars, spaces, dashes
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    if len(s) > max_len:
        s = s[:max_len].rsplit("-", 1)[0]
    return s or "story"


def generate_slug_map(stories: list[dict]) -> dict[str, str]:
    """Map story URL → unique slug, resolving collisions with -2, -3..."""
    slug_map: dict[str, str] = {}
    taken: dict[str, str] = {}
    for s in stories:
        if not s.get("approved"):
            continue
        url_src = s.get("url")
        if not url_src:
            continue
        base = slugify(s.get("title", "") or "story")
        slug = base
        i = 1
        while slug in taken and taken[slug] != url_src:
            i += 1
            slug = f"{base}-{i}"
        taken[slug] = url_src
        slug_map[url_src] = slug
    return slug_map


def format_date_human(iso: str) -> str:
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(iso.split("T")[0])
        return d.strftime("%B %d, %Y")
    except Exception:
        return iso


def format_date_iso(iso: str) -> str:
    if not iso:
        return ""
    return iso.split("T")[0]


def build_meta_description(story: dict) -> str:
    """Tight ~155-char description for Google snippet / OG."""
    excerpt = (story.get("excerpt") or "").strip()
    commentary = (story.get("vn_commentary") or "").strip()
    text = excerpt or commentary or story.get("title", "")
    if len(text) > 155:
        text = text[:152].rsplit(" ", 1)[0] + "…"
    return text


def paragraphize(text: str) -> str:
    """Split on double-newline or sentences, return HTML <p> blocks."""
    if not text:
        return ""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        paras = [text.strip()]
    return "".join(f"<p>{esc(p)}</p>" for p in paras)


def render_story_page(story: dict, slug: str) -> str:
    title = story.get("title", "Untitled")
    source = story.get("source", "")
    jurisdiction = story.get("jurisdiction", "")
    jur_abbr = JURISDICTION_ABBR.get(jurisdiction, jurisdiction)
    jur_class = "federal" if jurisdiction == "Federal" else ""
    published_at = story.get("published_at", "")
    pub_date_human = format_date_human(published_at)
    source_url = story.get("url", "")
    excerpt = story.get("excerpt", "")
    commentary = story.get("vn_commentary", "")
    tier_label = {1: "Regulator", 2: "News", 3: "Trade press"}.get(
        story.get("tier", 4), "Association"
    )
    is_update = bool(story.get("is_update"))
    categories = [CATEGORIES.get(c, c.title()) for c in (story.get("categories") or [])]

    meta_desc = build_meta_description(story)
    canonical = f"{HUB_URL}/stories/{slug}"

    page_title_raw = f"{title} | VantageNorth Compliance Hub"
    page_title = page_title_raw if len(page_title_raw) <= 90 else f"{title[:70]}… | VantageNorth Compliance Hub"
    og_title = title if len(title) <= 65 else title[:60].rsplit(" ", 1)[0] + "…"

    # JSON-LD: NewsArticle + Breadcrumb
    article_jsonld = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": title,
        "datePublished": published_at,
        "description": meta_desc,
        "url": canonical,
        "author": {"@type": "Organization", "name": "VantageNorth Compliance"},
        "publisher": {
            "@type": "Organization",
            "name": "VantageNorth Compliance",
            "logo": {"@type": "ImageObject", "url": f"{HUB_URL}/vantagenorth-logo.png"},
        },
        "isAccessibleForFree": True,
    }
    breadcrumbs = [
        {"@type": "ListItem", "position": 1, "name": "Compliance Hub", "item": f"{HUB_URL}/"},
    ]
    if jurisdiction:
        breadcrumbs.append(
            {"@type": "ListItem", "position": 2, "name": jurisdiction,
             "item": f"{HUB_URL}/#jurisdiction={jurisdiction.replace(' ', '%20')}"}
        )
    breadcrumbs.append(
        {"@type": "ListItem", "position": len(breadcrumbs) + 1, "name": title, "item": canonical}
    )
    breadcrumb_jsonld = {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": breadcrumbs,
    }

    # Breadcrumb HTML — short title to avoid overflow
    short_title = title if len(title) <= 65 else title[:62] + "…"
    jur_breadcrumb_html = (
        f'<span class="crumb-sep">›</span>'
        f'<a href="/#jurisdiction={jurisdiction.replace(" ", "%20")}">{esc(jurisdiction)}</a>'
        if jurisdiction else ""
    )

    update_pill = '<span class="pill update">UPDATE</span>' if is_update else ""
    commentary_html = (
        f'<aside class="vn-commentary">'
        f'<strong class="label">VantageNorth take</strong>'
        f'{paragraphize(commentary)}'
        f'</aside>'
        if commentary else ""
    )
    tags_html = "".join(f'<span class="tag">{esc(t)}</span>' for t in categories)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(page_title)}</title>
<meta name="description" content="{esc(meta_desc)}">
<meta name="author" content="VantageNorth Compliance">

<meta property="og:title" content="{esc(og_title)}">
<meta property="og:description" content="{esc(meta_desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="VantageNorth Compliance Hub">
<meta property="article:published_time" content="{esc(published_at)}">
<meta property="article:section" content="{esc(jurisdiction)}">

<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(og_title)}">
<meta name="twitter:description" content="{esc(meta_desc)}">

<link rel="canonical" href="{canonical}">
<link rel="icon" type="image/png" href="/favicon.png?v=hub2026">
<link rel="shortcut icon" type="image/png" href="/favicon.png?v=hub2026">
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png?v=hub2026">
<link rel="icon" type="image/png" sizes="64x64" href="/favicon-64.png?v=hub2026">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png?v=hub2026">

<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@600;700;800&display=swap" rel="stylesheet">

<style>
:root {{
  --navy: #122a44;
  --navy-deep: #0b1f36;
  --accent: #4a9b5e;
  --accent-light: #6cb47e;
  --accent-deep: #3a7d4a;
  --cream: #f7f6f1;
  --white: #ffffff;
  --text: #1a2638;
  --text-muted: #556479;
  --border: rgba(74,155,94,0.18);
  --shadow-sm: 0 2px 8px rgba(18,42,68,0.06);
  --shadow-md: 0 8px 30px rgba(18,42,68,0.1);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{
  font-family: 'DM Sans', system-ui, sans-serif;
  background: var(--cream);
  color: var(--text);
  line-height: 1.65;
  min-height: 100vh;
}}
header.site-header {{
  background: rgba(255,255,255,0.95);
  border-bottom: 1px solid var(--border);
  padding: 1rem 0;
  position: sticky; top: 0; z-index: 100;
  backdrop-filter: blur(10px);
}}
.header-inner {{
  max-width: 1300px; margin: 0 auto;
  padding: 0 1.5rem;
  display: flex; align-items: center; justify-content: space-between; gap: 1rem;
}}
.brand {{ display: flex; align-items: center; gap: 0.75rem; text-decoration: none; color: var(--navy); }}
.brand-mark {{ height: 68px; width: auto; flex-shrink: 0; display: block; }}
.brand-text {{ line-height: 1.1; border-left: 2px solid var(--border); margin-left: 0.3rem; padding: 0.3rem 0 0.3rem 0.95rem; }}
.brand-text .bot {{ font-size: 0.95rem; color: var(--accent-deep); font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; }}
.header-actions {{ display: flex; gap: 0.5rem; }}
.header-actions a {{
  color: var(--navy); text-decoration: none;
  font-size: 0.9rem; font-weight: 600;
  padding: 0.5rem 0.9rem; border-radius: 6px;
  transition: background 0.2s;
}}
.header-actions a:hover {{ background: rgba(74,155,94,0.08); color: var(--accent-deep); }}
.header-actions a.cta {{ background: var(--accent); color: var(--white); }}
.header-actions a.cta:hover {{ background: var(--accent-deep); color: var(--white); }}

.article-wrap {{
  max-width: 820px;
  margin: 2.5rem auto 1rem;
  padding: 0 1.5rem;
}}
.breadcrumb {{
  font-size: 0.82rem;
  color: var(--text-muted);
  margin-bottom: 1.25rem;
  display: flex; flex-wrap: wrap; align-items: center;
  gap: 0.35rem;
}}
.breadcrumb a {{ color: var(--accent-deep); text-decoration: none; font-weight: 600; }}
.breadcrumb a:hover {{ color: var(--accent); }}
.crumb-sep {{ color: var(--border); }}

.article-meta {{
  display: flex; flex-wrap: wrap; gap: 0.5rem;
  margin-bottom: 0.9rem;
}}
.pill {{
  display: inline-flex; align-items: center; gap: 0.25rem;
  padding: 0.28rem 0.65rem;
  border-radius: 4px;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.04em;
}}
.pill.jur {{ background: var(--accent); color: var(--white); text-transform: uppercase; }}
.pill.jur.federal {{ background: var(--navy); }}
.pill.tier {{ background: rgba(74,155,94,0.12); color: var(--accent-deep); text-transform: uppercase; }}
.pill.update {{ background: #c58a2e; color: var(--white); text-transform: uppercase; letter-spacing: 0.06em; font-weight: 800; }}

h1.article-title {{
  font-family: 'Playfair Display', Georgia, serif;
  font-size: clamp(1.7rem, 4.5vw, 2.5rem);
  font-weight: 700;
  line-height: 1.2;
  color: var(--navy);
  margin-bottom: 0.75rem;
}}

.article-byline {{
  color: var(--text-muted);
  font-size: 0.92rem;
  margin-bottom: 1.75rem;
  padding-bottom: 1.5rem;
  border-bottom: 1px solid var(--border);
}}
.article-byline strong {{ color: var(--text); font-weight: 600; }}

.article-excerpt {{
  font-size: 1.05rem;
  line-height: 1.7;
  margin-bottom: 1.5rem;
  color: var(--text);
}}

.vn-commentary {{
  background: var(--white);
  border-left: 4px solid var(--accent);
  padding: 1.4rem 1.6rem 1.1rem;
  margin: 1.75rem 0 2rem;
  font-size: 1rem;
  line-height: 1.7;
  color: var(--text);
  border-radius: 0 10px 10px 0;
  box-shadow: var(--shadow-sm);
}}
.vn-commentary strong.label {{
  display: block;
  font-size: 0.75rem;
  color: var(--accent-deep);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  margin-bottom: 0.65rem;
  font-weight: 700;
  font-family: 'DM Sans', system-ui, sans-serif;
}}
.vn-commentary p {{ margin-bottom: 0.9rem; }}
.vn-commentary p:last-child {{ margin-bottom: 0; }}

.source-box {{
  background: var(--white);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 1.25rem 1.5rem;
  margin: 2rem 0 1.5rem;
}}
.source-box .label {{
  display: block;
  font-size: 0.72rem;
  color: var(--text-muted);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  font-weight: 700;
  margin-bottom: 0.5rem;
}}
.source-box .source-name {{
  font-weight: 700;
  color: var(--navy);
  font-size: 1.05rem;
  margin-bottom: 0.2rem;
}}
.source-box a.source-link {{
  display: inline-flex; align-items: center; gap: 0.4rem;
  color: var(--accent-deep);
  text-decoration: none;
  font-size: 0.95rem;
  font-weight: 700;
  margin-top: 0.6rem;
}}
.source-box a.source-link:hover {{ color: var(--accent); }}
.source-box a.source-link::after {{ content: ' ↗'; }}

.tag-row {{
  display: flex; flex-wrap: wrap; gap: 0.35rem;
  margin: 1.5rem 0;
}}
.tag {{
  font-size: 0.72rem;
  padding: 0.28rem 0.65rem;
  background: var(--white);
  border: 1px solid var(--border);
  color: var(--text-muted);
  border-radius: 4px;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}}

.cta-row {{
  display: flex; gap: 0.75rem; flex-wrap: wrap;
  margin-top: 2.25rem;
  padding-top: 1.75rem;
  border-top: 1px solid var(--border);
}}
.cta-row a {{
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.65rem 1.1rem;
  border-radius: 6px;
  text-decoration: none;
  font-size: 0.9rem;
  font-weight: 700;
  transition: background 0.15s, color 0.15s;
}}
.cta-row a.primary {{ background: var(--accent); color: var(--white); }}
.cta-row a.primary:hover {{ background: var(--accent-deep); }}
.cta-row a.secondary {{ background: transparent; color: var(--accent-deep); border: 1px solid var(--border); }}
.cta-row a.secondary:hover {{ background: rgba(74,155,94,0.06); border-color: var(--accent); }}
.cta-row a.back {{ color: var(--text-muted); text-decoration: none; font-weight: 600; display: inline-flex; align-items: center; margin-right: auto; }}
.cta-row a.back::before {{ content: '← '; margin-right: 0.3rem; }}
.cta-row a.back:hover {{ color: var(--accent-deep); }}

footer {{
  background: var(--navy-deep);
  color: rgba(255,255,255,0.7);
  padding: 2.5rem 1.5rem 1.5rem;
  margin-top: 3rem;
}}
.footer-inner {{
  max-width: 1100px; margin: 0 auto;
  display: flex; justify-content: space-between; align-items: center;
  flex-wrap: wrap; gap: 1rem;
}}
.footer-inner a {{ color: var(--accent-light); text-decoration: none; font-weight: 600; }}
.footer-inner a:hover {{ color: var(--white); }}

@media (max-width: 640px) {{
  .article-wrap {{ margin: 1.5rem auto; }}
  h1.article-title {{ font-size: 1.6rem; }}
  .brand-mark {{ height: 52px; }}
  .brand-text .bot {{ font-size: 0.72rem; }}
  .header-actions a {{ padding: 0.4rem 0.7rem; font-size: 0.82rem; }}
  .cta-row {{ flex-direction: column; align-items: stretch; }}
  .cta-row a.back {{ margin-right: 0; order: 10; text-align: center; }}
}}
</style>

<script type="application/ld+json">
{json.dumps(article_jsonld, separators=(",", ":"))}
</script>
<script type="application/ld+json">
{json.dumps(breadcrumb_jsonld, separators=(",", ":"))}
</script>
</head>
<body>

<header class="site-header">
  <div class="header-inner">
    <a href="/" class="brand" aria-label="VantageNorth Compliance Hub">
      <img class="brand-mark" src="/vantagenorth-logo.png" alt="VantageNorth Compliance">
      <span class="brand-text">
        <span class="bot">The Compliance Hub</span>
      </span>
    </a>
    <nav class="header-actions">
      <a href="/">All Stories</a>
      <a href="https://www.vantagenorth.ca/" >Main Site</a>
      <a href="https://www.vantagenorth.ca/#cta" class="cta">Get in Touch</a>
    </nav>
  </div>
</header>

<article class="article-wrap">
  <div class="breadcrumb">
    <a href="/">Compliance Hub</a>{jur_breadcrumb_html}
    <span class="crumb-sep">›</span>{esc(short_title)}
  </div>

  <div class="article-meta">
    {f'<span class="pill jur {jur_class}">{esc(jur_abbr)}</span>' if jur_abbr else ''}
    <span class="pill tier">{esc(tier_label)}</span>
    {update_pill}
  </div>

  <h1 class="article-title">{esc(title)}</h1>

  <div class="article-byline">
    Published {esc(pub_date_human)} · Source: <strong>{esc(source)}</strong>
  </div>

  <div class="article-excerpt">{esc(excerpt)}</div>

  {commentary_html}

  <div class="source-box">
    <span class="label">Original Source</span>
    <div class="source-name">{esc(source)}</div>
    <a href="{esc(source_url)}" class="source-link" target="_blank" rel="noopener">Read the full article</a>
  </div>

  <div class="tag-row">{tags_html}</div>

  <div class="cta-row">
    <a href="/" class="back">Back to the Compliance Hub</a>
    <a href="https://www.vantagenorth.ca/#cta" class="primary">Work with VantageNorth</a>
  </div>
</article>

<footer>
  <div class="footer-inner">
    <div>© 2026 <a href="https://www.vantagenorth.ca/">VantageNorth Compliance</a> · Calgary, Alberta</div>
    <div>
      <a href="https://www.linkedin.com/company/vantagenorth-compliance/" target="_blank" rel="noopener">LinkedIn</a>
      &nbsp;·&nbsp;
      <a href="https://www.vantagenorth.ca/#cta">Contact</a>
    </div>
  </div>
</footer>

</body>
</html>'''


def build_sitemap(stories: list[dict], slug_map: dict[str, str]) -> str:
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = [
        f'  <url><loc>{HUB_URL}/</loc><lastmod>{today_iso}</lastmod>'
        f'<changefreq>daily</changefreq><priority>1.0</priority></url>'
    ]
    for s in stories:
        if not s.get("approved"):
            continue
        slug = slug_map.get(s.get("url"))
        if not slug:
            continue
        lastmod = format_date_iso(s.get("published_at") or s.get("added_at", "")) or today_iso
        entries.append(
            f'  <url><loc>{HUB_URL}/stories/{slug}</loc>'
            f'<lastmod>{lastmod}</lastmod>'
            f'<changefreq>weekly</changefreq><priority>0.8</priority></url>'
        )
    body = "\n".join(entries)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'{body}\n'
        '</urlset>\n'
    )


def main() -> int:
    print(f"[build] Reading {STORIES_JSON}")
    with open(STORIES_JSON) as f:
        stories = json.load(f)

    approved = [s for s in stories if s.get("approved")]
    print(f"[build] {len(approved)} approved / {len(stories)} total")

    STORIES_DIR.mkdir(parents=True, exist_ok=True)
    # Nuke old pages so deleted/renamed stories don't linger
    for old in STORIES_DIR.glob("*.html"):
        old.unlink()

    slug_map = generate_slug_map(stories)

    written = 0
    for s in approved:
        url_src = s.get("url")
        slug = slug_map.get(url_src)
        if not slug:
            continue
        page = render_story_page(s, slug)
        (STORIES_DIR / f"{slug}.html").write_text(page, encoding="utf-8")
        written += 1
    print(f"[build] Wrote {written} story pages into {STORIES_DIR}")

    # Sitemap
    SITEMAP_PATH.write_text(build_sitemap(stories, slug_map), encoding="utf-8")
    print(f"[build] Wrote sitemap ({written + 1} URLs)")

    # Slug map (used by hub.js to render per-story card links)
    SLUG_MAP_PATH.write_text(json.dumps(slug_map, indent=2), encoding="utf-8")
    print(f"[build] Wrote slug-map.json ({len(slug_map)} entries)")

    # Copy stories.json into site for hub.js local fallback
    SITE_STORIES_JSON.write_text(STORIES_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[build] Copied stories.json into site/")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
