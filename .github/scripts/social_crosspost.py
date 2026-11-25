#!/usr/bin/env python3
"""
VantageNorth Social Cross-Post
Runs inside GitHub Actions when stories.json changes on main.
Picks the top newly-added story from that commit and posts to Facebook (+ X when configured).
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
STORIES_PATH = REPO_ROOT / "stories.json"
STATE_PATH = REPO_ROOT / ".github" / "last_post_state.json"
HUB_URL = "https://hub.vantagenorth.ca"

# =====================================================================
# Helpers
# =====================================================================

def log(msg: str) -> None:
    print(f"[crosspost] {msg}", flush=True)


def get_previous_stories_json() -> list[dict]:
    """Read stories.json as it existed BEFORE this commit."""
    try:
        prev_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD~1"], cwd=REPO_ROOT, text=True
        ).strip()
        prev_content = subprocess.check_output(
            ["git", "show", f"{prev_sha}:stories.json"], cwd=REPO_ROOT, text=True
        )
        return json.loads(prev_content)
    except subprocess.CalledProcessError:
        log("No previous commit to diff against; treating all stories as new.")
        return []


def get_current_stories_json() -> list[dict]:
    with open(STORIES_PATH, "r") as f:
        return json.load(f)


def pick_crosspost_story() -> dict | None:
    """Pick the best story for cross-posting.

    On a push event: look at stories added in this commit vs its parent.
    On a manual workflow_dispatch: fall back to the most recent approved story,
    so tests always have something to post.
    """
    current = get_current_stories_json()
    event_name = os.environ.get("GITHUB_EVENT_NAME", "").strip()

    if event_name == "workflow_dispatch":
        # Manual run — pick the most recently added approved story regardless of diff
        approved = [s for s in current if s.get("approved", False) and s.get("url")]
        approved.sort(
            key=lambda s: (s.get("added_at", ""), s.get("published_at", "")),
            reverse=True,
        )
        if not approved:
            log("No approved stories at all; nothing to post.")
            return None
        top = approved[0]
        log(f"Manual run — picked most recent approved: [{top.get('tier','?')}|{top.get('score','?')}] {top.get('title','')[:80]}")
        return top

    # Normal (push) path — only post stories newly added in this commit
    previous = get_previous_stories_json()
    prev_urls = {s.get("url") for s in previous if s.get("url")}
    new_stories = [
        s for s in current
        if s.get("url") and s["url"] not in prev_urls and s.get("approved", False)
    ]
    log(f"Found {len(new_stories)} new approved stories in this commit.")
    if not new_stories:
        return None

    # Rank: tier (lower is better — tier 1 is CRITICAL), then score (higher is better)
    new_stories.sort(key=lambda s: (s.get("tier", 99), -s.get("score", 0)))
    top = new_stories[0]
    log(f"Top pick: [{top.get('tier','?')}|{top.get('score','?')}] {top.get('title','')[:80]}")
    return top


def already_posted_today() -> bool:
    """Check if we already posted a story in the last ~20 hours."""
    if not STATE_PATH.exists():
        return False
    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
        last = state.get("last_facebook_post_at")
        if not last:
            return False
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        age_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        return age_hours < 20
    except Exception as e:
        log(f"State check failed, allowing post: {e}")
        return False


def record_post(story: dict, fb_post_id: str | None = None, x_post_id: str | None = None) -> None:
    state = {}
    if STATE_PATH.exists():
        try:
            with open(STATE_PATH) as f:
                state = json.load(f)
        except Exception:
            state = {}
    state["last_facebook_post_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    state["last_story_url"] = story.get("url")
    state["last_story_title"] = story.get("title")
    state["last_facebook_post_id"] = fb_post_id
    state["last_x_post_id"] = x_post_id
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
    log(f"Recorded post state at {STATE_PATH}")


# =====================================================================
# Facebook
# =====================================================================

def format_facebook_post(story: dict) -> str:
    """Build the Facebook post body in Garry's voice."""
    title = story.get("title", "").strip()
    excerpt = story.get("excerpt", "").strip()
    commentary = (story.get("vn_commentary") or "").strip()
    url = story.get("url", "").strip()
    jurisdiction = story.get("jurisdiction", "")

    # Header
    parts = [f"📋 {title}"]
    if jurisdiction:
        parts.append(f"({jurisdiction})")
    parts = [" ".join(parts)]

    # Excerpt if short enough
    if excerpt and len(excerpt) < 400:
        parts.append(excerpt)

    # Commentary (Garry's voice)
    if commentary:
        parts.append(commentary)

    # Links
    parts.append(f"Full story: {url}")
    parts.append(f"More Western Canada compliance intel: {HUB_URL}")

    body = "\n\n".join(parts)
    # FB soft limit is ~63,000 chars; we're well under
    return body


def resolve_fb_page_id(token: str) -> str | None:
    """If FB_PAGE_ID isn't set, derive it from the token by calling /me."""
    try:
        resp = requests.get(
            "https://graph.facebook.com/v27.0/me",
            params={"fields": "id,name", "access_token": token},
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            page_id = data.get("id")
            page_name = data.get("name", "")
            log(f"Resolved Page ID {page_id} ({page_name}) from token.")
            return page_id
        log(f"Could not resolve Page ID: HTTP {resp.status_code} — {resp.text[:300]}")
    except Exception as e:
        log(f"Page ID resolve error: {e}")
    return None


def post_to_facebook(story: dict) -> str | None:
    fb_page_token = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not fb_page_token:
        log("FB_PAGE_TOKEN missing; skipping Facebook.")
        return None
    fb_page_id = os.environ.get("FB_PAGE_ID", "").strip()
    if not fb_page_id:
        fb_page_id = resolve_fb_page_id(fb_page_token)
    if not fb_page_id:
        log("Could not determine Page ID; skipping Facebook.")
        return None

    body = format_facebook_post(story)
    story_url = story.get("url", "")

    log(f"Posting to Facebook page {fb_page_id} ({len(body)} chars)")
    resp = requests.post(
        f"https://graph.facebook.com/v27.0/{fb_page_id}/feed",
        data={
            "message": body,
            "link": story_url,
            "access_token": fb_page_token,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        log(f"Facebook post FAILED: HTTP {resp.status_code} — {resp.text[:500]}")
        return None
    data = resp.json()
    post_id = data.get("id", "unknown")
    log(f"✅ Facebook post created: {post_id}")
    return post_id


# =====================================================================
# X (Twitter)
# =====================================================================

def format_x_post(story: dict) -> str:
    """X post, under 280 chars, with Hub URL as the trackable link."""
    title = story.get("title", "").strip()
    # Reserve ~25 chars for URL + spacing
    max_title = 240
    if len(title) > max_title:
        title = title[: max_title - 1] + "…"
    return f"{title}\n\n{HUB_URL}"


def post_to_x(story: dict) -> str | None:
    """Post to X using OAuth 1.0a user context."""
    api_key = os.environ.get("X_API_KEY", "").strip()
    api_secret = os.environ.get("X_API_SECRET", "").strip()
    access_token = os.environ.get("X_ACCESS_TOKEN", "").strip()
    access_secret = os.environ.get("X_ACCESS_SECRET", "").strip()
    if not all([api_key, api_secret, access_token, access_secret]):
        log("X credentials incomplete; skipping X. (Add FB first, X later.)")
        return None

    try:
        from requests_oauthlib import OAuth1
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests-oauthlib"])
        from requests_oauthlib import OAuth1

    text = format_x_post(story)
    log(f"Posting to X ({len(text)} chars)")
    auth = OAuth1(api_key, api_secret, access_token, access_secret)
    resp = requests.post(
        "https://api.twitter.com/2/tweets",
        auth=auth,
        json={"text": text},
        timeout=30,
    )
    if resp.status_code not in (200, 201):
        log(f"X post FAILED: HTTP {resp.status_code} — {resp.text[:500]}")
        return None
    data = resp.json()
    post_id = data.get("data", {}).get("id", "unknown")
    log(f"✅ X post created: {post_id}")
    return post_id


# =====================================================================
# Main
# =====================================================================

def main() -> int:
    log(f"Started at {datetime.now(timezone.utc).isoformat()}")

    if os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"):
        log("DRY_RUN set; will not actually post.")

    if already_posted_today():
        log("Already posted in the last 20 hours; skipping.")
        return 0

    story = pick_crosspost_story()
    if not story:
        log("No new approved stories to cross-post. Exiting.")
        return 0

    log(f"\n--- Facebook preview ---\n{format_facebook_post(story)}\n--- end ---\n")
    log(f"\n--- X preview ---\n{format_x_post(story)}\n--- end ---\n")

    if os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes"):
        log("DRY_RUN complete; not posting, not recording state.")
        return 0

    fb_id = post_to_facebook(story)
    x_id = post_to_x(story)

    if fb_id or x_id:
        record_post(story, fb_post_id=fb_id, x_post_id=x_id)
    else:
        log("No successful posts; not recording state.")
        return 1

    log("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
