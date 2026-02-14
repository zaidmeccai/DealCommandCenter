"""Deal analysis engine - uses Claude API to generate insights from deal data."""

import logging
from datetime import date

import anthropic

from .avoma_client import AvomaMeeting
from .salesforce_client import Opportunity

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 4096


def _format_meeting_context(meetings: list[AvomaMeeting], max_meetings: int = 3) -> str:
    """Format recent meetings into context string for Claude."""
    if not meetings:
        return "No recent meetings found in Avoma."

    parts = []
    for m in meetings[:max_meetings]:
        date_str = m.meeting_date.strftime("%Y-%m-%d")
        participants_str = ", ".join(m.participants[:5])
        topics_str = ", ".join(m.key_topics[:5]) if m.key_topics else "No topics extracted"
        action_items_str = "\n".join(
            f"  - {'[DONE] ' if ai.completed else '[ ] '}{ai.text}"
            + (f" (assigned to: {ai.assignee})" if ai.assignee else "")
            + (f" (due: {ai.due_date})" if ai.due_date else "")
            for ai in m.action_items
        ) if m.action_items else "  None recorded"

        # Include transcript excerpt if available (first 1500 chars)
        transcript_excerpt = ""
        if m.transcript_text:
            excerpt = m.transcript_text[:1500]
            transcript_excerpt = f"\n  Transcript excerpt: {excerpt}"

        parts.append(
            f"Meeting: {m.title} ({date_str})\n"
            f"  Participants: {participants_str}\n"
            f"  Topics: {topics_str}\n"
            f"  Summary: {m.summary or 'No summary available'}\n"
            f"  Action items:\n{action_items_str}"
            f"{transcript_excerpt}"
        )

    return "\n\n".join(parts)


def _format_local_context(local_context: dict[str, str]) -> str:
    """Format local deal folder files into context string."""
    if not local_context:
        return ""

    parts = []
    for filename, content in local_context.items():
        parts.append(f"--- {filename} ---\n{content}")

    return "\n\n".join(parts)


class DealAnalyzer:
    """Generates AI-powered insights for deals using Claude."""

    def __init__(self, api_key: str):
        self._client = anthropic.Anthropic(api_key=api_key)

    def generate_call_prep(self, opp: Opportunity, calendar_entry: str = "") -> str:
        """Generate pre-call talking points and intel for an upcoming call."""
        meeting_ctx = _format_meeting_context(opp.avoma_meetings)
        local_ctx = _format_local_context(opp.local_context)

        prompt = f"""You are a deal strategy advisor for an enterprise AE selling conversational AI for debt collections.

Analyze this deal and generate a pre-call brief.

OPPORTUNITY:
- Account: {opp.account_name}
- Opportunity: {opp.name}
- Stage: {opp.stage}
- Amount: ${opp.amount:,.0f}
- Close Date: {opp.close_date or 'Not set'}
- Days Since Last Activity: {opp.days_since_last_activity or 'Unknown'}
- Next Steps (from SF): {opp.next_step or 'None recorded'}

RECENT AVOMA MEETINGS:
{meeting_ctx}

{"LOCAL DEAL CONTEXT:" + chr(10) + local_ctx if local_ctx else ""}

{"TODAY'S CALENDAR ENTRY: " + calendar_entry if calendar_entry else ""}

Generate:
1. A 2-3 sentence summary of the last conversation
2. Key pain points or objections identified so far
3. Pending action items from me that I should address
4. 3-4 specific talking points for today's call based on deal stage, history, and any commitments made
5. Any commitments I made that I should reference

Keep it concise and actionable. Use bullet points. Focus on what matters most for advancing this deal."""

        return self._call_claude(prompt)

    def generate_risk_assessment(self, at_risk_opps: list[Opportunity]) -> str:
        """Generate risk analysis and suggested next steps for stalled deals."""
        if not at_risk_opps:
            return ""

        deal_summaries = []
        for opp in at_risk_opps:
            meeting_ctx = _format_meeting_context(opp.avoma_meetings, max_meetings=1)
            deal_summaries.append(
                f"- {opp.account_name}: Stage={opp.stage}, "
                f"Amount=${opp.amount:,.0f}, "
                f"Last Activity={opp.days_since_last_activity} days ago, "
                f"Close Date={opp.close_date or 'Not set'}\n"
                f"  Next Steps: {opp.next_step or 'None'}\n"
                f"  Last meeting context: {meeting_ctx[:300]}"
            )

        prompt = f"""You are a deal strategy advisor. These deals have gone 5+ days without activity and may be at risk.

AT-RISK DEALS:
{chr(10).join(deal_summaries)}

For each deal, provide:
1. A brief assessment of why it might be stalling
2. One specific, actionable next step to re-engage

Keep each suggestion to 1-2 sentences. Be direct and specific."""

        return self._call_claude(prompt)

    def generate_priority_recommendations(self, opportunities: list[Opportunity]) -> str:
        """Identify the 2-3 deals that should get the most attention today."""
        today = date.today()

        deal_data = []
        for opp in opportunities:
            days_to_close = (opp.close_date - today).days if opp.close_date else 999
            meeting_count = len(opp.avoma_meetings)
            pending_actions = sum(
                len([ai for ai in m.action_items if not ai.completed])
                for m in opp.avoma_meetings[:2]
            )

            deal_data.append(
                f"- {opp.account_name}: ${opp.amount:,.0f}, Stage={opp.stage}, "
                f"Closes in {days_to_close} days, "
                f"Last activity {opp.days_since_last_activity or '?'} days ago, "
                f"{meeting_count} recent meetings, {pending_actions} pending actions, "
                f"Next Steps: {opp.next_step or 'None'}"
            )

        prompt = f"""You are a deal strategy advisor for an enterprise AE. Based on this pipeline, identify the TOP 2-3 deals that deserve the most attention today.

Consider: close date proximity, deal size, stage momentum, staleness, pending actions.

PIPELINE:
{chr(10).join(deal_data)}

For each priority deal:
1. Why it's a priority right now
2. One specific action to take today

Rank them 1-3 and keep it concise."""

        return self._call_claude(prompt)

    def _call_claude(self, prompt: str) -> str:
        """Make a Claude API call with error handling."""
        try:
            message = self._client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
        except anthropic.RateLimitError:
            logger.warning("Claude API rate limited, returning placeholder")
            return "[Analysis unavailable - API rate limited. Try again shortly.]"
        except anthropic.APIError as exc:
            logger.error("Claude API error: %s", exc)
            return f"[Analysis unavailable - API error: {exc}]"
        except Exception as exc:
            logger.error("Unexpected error calling Claude: %s", exc)
            return f"[Analysis unavailable - error: {exc}]"
