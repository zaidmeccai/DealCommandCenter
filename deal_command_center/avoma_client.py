"""Avoma integration - pull meeting transcripts and action items."""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / "avoma_cache"
CACHE_EXPIRY_HOURS = 12

# Avoma API base - update if their docs specify a different base URL
AVOMA_API_BASE = "https://api.avoma.com/v1"


@dataclass
class ActionItem:
    text: str
    assignee: str
    due_date: date | None
    completed: bool


@dataclass
class AvomaMeeting:
    id: str
    title: str
    meeting_date: datetime
    participants: list[str]
    summary: str
    key_topics: list[str]
    action_items: list[ActionItem]
    transcript_text: str
    account_name_hint: str = ""


class AvomaClient:
    """Client for Avoma API with local caching."""

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        CACHE_DIR.mkdir(exist_ok=True)

    def _cache_key(self, endpoint: str, params: dict) -> str:
        raw = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_cached(self, cache_key: str) -> dict | None:
        cache_file = CACHE_DIR / f"{cache_key}.json"
        if not cache_file.exists():
            return None
        try:
            data = json.loads(cache_file.read_text())
            cached_at = datetime.fromisoformat(data.get("_cached_at", ""))
            if datetime.now() - cached_at > timedelta(hours=CACHE_EXPIRY_HOURS):
                cache_file.unlink(missing_ok=True)
                return None
            return data.get("payload")
        except (json.JSONDecodeError, ValueError):
            cache_file.unlink(missing_ok=True)
            return None

    def _set_cache(self, cache_key: str, payload: dict) -> None:
        cache_file = CACHE_DIR / f"{cache_key}.json"
        data = {"_cached_at": datetime.now().isoformat(), "payload": payload}
        cache_file.write_text(json.dumps(data))

    def _api_get(self, endpoint: str, params: dict | None = None, use_cache: bool = True) -> dict | None:
        params = params or {}
        ck = self._cache_key(endpoint, params)

        if use_cache:
            cached = self._get_cached(ck)
            if cached is not None:
                logger.debug("Avoma: cache hit for %s", endpoint)
                return cached

        url = f"{AVOMA_API_BASE}/{endpoint.lstrip('/')}"
        retries = 3
        for attempt in range(retries):
            try:
                resp = self._session.get(url, params=params, timeout=30)
                if resp.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    logger.warning("Avoma: rate limited, waiting %ds", wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                payload = resp.json()
                if use_cache:
                    self._set_cache(ck, payload)
                return payload
            except requests.RequestException as exc:
                logger.warning("Avoma API error (attempt %d/%d): %s", attempt + 1, retries, exc)
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)

        logger.error("Avoma: all retries exhausted for %s", endpoint)
        return None

    def get_recent_meetings(self, days: int = 30) -> list[AvomaMeeting]:
        """Fetch meetings from the last N days."""
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        data = self._api_get("meetings", params={"from_date": since, "limit": 100})

        if not data:
            logger.warning("Avoma: no meeting data returned")
            return []

        meetings_raw = data if isinstance(data, list) else data.get("meetings", data.get("results", []))
        meetings: list[AvomaMeeting] = []

        for m in meetings_raw:
            meeting = self._parse_meeting(m)
            if meeting:
                meetings.append(meeting)

        logger.info("Avoma: fetched %d meetings from last %d days", len(meetings), days)
        return meetings

    def get_meeting_details(self, meeting_id: str) -> AvomaMeeting | None:
        """Fetch detailed transcript and notes for a single meeting."""
        data = self._api_get(f"meetings/{meeting_id}")
        if not data:
            return None
        return self._parse_meeting(data)

    def _parse_meeting(self, m: dict) -> AvomaMeeting | None:
        try:
            meeting_date_str = m.get("date") or m.get("start_time") or m.get("scheduled_at", "")
            if meeting_date_str:
                meeting_date = datetime.fromisoformat(meeting_date_str.replace("Z", "+00:00"))
            else:
                meeting_date = datetime.now()

            participants = []
            for p in m.get("participants", m.get("attendees", [])):
                if isinstance(p, str):
                    participants.append(p)
                elif isinstance(p, dict):
                    participants.append(p.get("name") or p.get("email", "Unknown"))

            action_items = []
            for ai in m.get("action_items", m.get("actionItems", [])):
                if isinstance(ai, str):
                    action_items.append(ActionItem(text=ai, assignee="", due_date=None, completed=False))
                elif isinstance(ai, dict):
                    due_str = ai.get("due_date") or ai.get("dueDate")
                    due_dt = None
                    if due_str:
                        try:
                            due_dt = datetime.strptime(due_str[:10], "%Y-%m-%d").date()
                        except ValueError:
                            pass
                    action_items.append(ActionItem(
                        text=ai.get("text") or ai.get("description", ""),
                        assignee=ai.get("assignee") or ai.get("owner", ""),
                        due_date=due_dt,
                        completed=ai.get("completed", False),
                    ))

            key_topics = m.get("key_topics", m.get("topics", []))
            if isinstance(key_topics, list) and key_topics and isinstance(key_topics[0], dict):
                key_topics = [t.get("name", str(t)) for t in key_topics]

            summary = m.get("summary") or m.get("notes") or m.get("ai_summary", "")
            transcript = m.get("transcript") or m.get("transcript_text", "")
            if isinstance(transcript, list):
                transcript = "\n".join(
                    f"{seg.get('speaker', '')}: {seg.get('text', '')}" for seg in transcript
                )

            # Try to extract account name from meeting title
            title = m.get("title") or m.get("subject", "Untitled Meeting")

            return AvomaMeeting(
                id=m.get("id") or m.get("uuid", ""),
                title=title,
                meeting_date=meeting_date,
                participants=participants,
                summary=summary,
                key_topics=key_topics,
                action_items=action_items,
                transcript_text=transcript if isinstance(transcript, str) else "",
                account_name_hint=title,
            )
        except Exception as exc:
            logger.warning("Avoma: failed to parse meeting: %s", exc)
            return None

    def clear_cache(self) -> int:
        """Remove all cached files. Returns count of files removed."""
        count = 0
        for f in CACHE_DIR.glob("*.json"):
            f.unlink()
            count += 1
        return count
