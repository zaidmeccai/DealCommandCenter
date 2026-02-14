"""Data matching engine - links Avoma meetings and local files to Salesforce opportunities."""

import logging
from difflib import SequenceMatcher

from .avoma_client import AvomaMeeting
from .salesforce_client import Opportunity

logger = logging.getLogger(__name__)

# Minimum similarity score to consider a match
MATCH_THRESHOLD = 0.55


def _normalize(name: str) -> str:
    """Lowercase and strip common suffixes for matching."""
    name = name.lower().strip()
    for suffix in [" inc", " inc.", " llc", " corp", " corp.", " ltd", " ltd.",
                   " co", " co.", " group", " holdings"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name


def _similarity(a: str, b: str) -> float:
    """Compute similarity between two strings."""
    return SequenceMatcher(None, a, b).ratio()


def _account_in_text(account_name: str, text: str) -> bool:
    """Check if account name (or significant portion) appears in text."""
    norm_account = _normalize(account_name)
    norm_text = text.lower()

    # Direct substring match
    if norm_account in norm_text:
        return True

    # Check each significant word (3+ chars) of the account name
    words = [w for w in norm_account.split() if len(w) >= 3]
    if words and all(w in norm_text for w in words):
        return True

    return False


def match_meetings_to_opportunities(
    opportunities: list[Opportunity],
    meetings: list[AvomaMeeting],
) -> list[Opportunity]:
    """Attach matching Avoma meetings to each opportunity. Modifies opps in-place and returns them."""

    for opp in opportunities:
        norm_account = _normalize(opp.account_name)
        matched: list[AvomaMeeting] = []

        for meeting in meetings:
            # Check meeting title
            if _account_in_text(opp.account_name, meeting.title):
                matched.append(meeting)
                continue

            # Check participants for company domain hints
            if _account_in_text(opp.account_name, " ".join(meeting.participants)):
                matched.append(meeting)
                continue

            # Fuzzy match on title
            norm_title = _normalize(meeting.title)
            if _similarity(norm_account, norm_title) >= MATCH_THRESHOLD:
                matched.append(meeting)
                continue

            # Check summary/transcript for account name
            if meeting.summary and _account_in_text(opp.account_name, meeting.summary):
                matched.append(meeting)
                continue

        # Sort by date descending (most recent first)
        matched.sort(key=lambda m: m.meeting_date, reverse=True)
        opp.avoma_meetings = matched

        if matched:
            logger.debug(
                "Matched %d meetings to %s", len(matched), opp.account_name
            )

    return opportunities


def match_local_deals_to_opportunities(
    opportunities: list[Opportunity],
    local_deals: dict[str, dict[str, str]],
) -> list[Opportunity]:
    """Attach local deal folder content to matching opportunities."""

    for opp in opportunities:
        norm_account = _normalize(opp.account_name)
        best_match_key = None
        best_score = 0.0

        for folder_key in local_deals:
            # Direct substring match
            if norm_account in folder_key or folder_key in norm_account:
                best_match_key = folder_key
                break

            score = _similarity(norm_account, folder_key)
            if score > best_score and score >= MATCH_THRESHOLD:
                best_score = score
                best_match_key = folder_key

        if best_match_key:
            opp.local_context = local_deals[best_match_key]
            logger.debug("Matched local folder '%s' to %s", best_match_key, opp.account_name)

    return opportunities
