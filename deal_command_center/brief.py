"""Brief generator - formats all sections into a scannable daily brief."""

from datetime import date

from .avoma_client import AvomaMeeting
from .salesforce_client import Opportunity

LINE = "\u2500" * 50
DOUBLE_LINE = "\u2550" * 50


def _fmt_amount(amount: float) -> str:
    if amount >= 1_000_000:
        return f"${amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"${amount / 1_000:.0f}k"
    return f"${amount:,.0f}"


def _fmt_date(d: date | None) -> str:
    return d.strftime("%m/%d") if d else "No date"


def generate_brief(
    opportunities: list[Opportunity],
    calendar_matches: list[tuple[str, Opportunity | None]],
    call_preps: dict[str, str],
    risk_analysis: str,
    priority_analysis: str,
) -> str:
    """Generate the full daily brief as a formatted string."""
    today = date.today()
    sections: list[str] = []

    # ── Header ──
    sections.append(f"""
{DOUBLE_LINE}
  DAILY DEAL BRIEF - {today.strftime('%A, %B %d, %Y')}
{DOUBLE_LINE}""")

    # ── Pipeline Snapshot ──
    total_pipeline = sum(o.amount for o in opportunities)
    closing_this_month = [o for o in opportunities if o.closes_this_month]
    closing_this_quarter = [o for o in opportunities if o.closes_this_quarter]
    month_value = sum(o.amount for o in closing_this_month)
    quarter_value = sum(o.amount for o in closing_this_quarter)

    stage_counts: dict[str, int] = {}
    for o in opportunities:
        stage_counts[o.stage] = stage_counts.get(o.stage, 0) + 1

    stage_summary = " | ".join(f"{s}: {c}" for s, c in sorted(stage_counts.items()))

    sections.append(f"""
PIPELINE SNAPSHOT
{LINE}
Total Open Pipeline: {_fmt_amount(total_pipeline)} ({len(opportunities)} deals)
Closing This Month:  {_fmt_amount(month_value)} ({len(closing_this_month)} deals)
Closing This Quarter: {_fmt_amount(quarter_value)} ({len(closing_this_quarter)} deals)
By Stage: {stage_summary}""")

    # ── Today's Calls ──
    calls_section = f"""
TODAY'S CALLS
{LINE}"""

    if not calendar_matches:
        calls_section += "\nNo calendar provided or no calls matched to deals today."
    else:
        for cal_entry, opp in calendar_matches:
            if opp:
                calls_section += f"""
[DEAL] {opp.account_name} - {opp.name}
       Stage: {opp.stage} | Amount: {_fmt_amount(opp.amount)} | Closes: {_fmt_date(opp.close_date)}
       Calendar: {cal_entry}
"""
                # Add Avoma meeting context
                if opp.avoma_meetings:
                    last_meeting = opp.avoma_meetings[0]
                    calls_section += _format_last_meeting(last_meeting)

                # Add pending action items across recent meetings
                pending = _collect_pending_actions(opp.avoma_meetings)
                if pending:
                    calls_section += "\n       Pending action items from me:\n"
                    for item in pending[:5]:
                        calls_section += f"       * {item}\n"

                # Add AI-generated call prep
                prep = call_preps.get(opp.account_name)
                if prep:
                    calls_section += f"\n       --- AI Prep Notes ---\n"
                    for line in prep.strip().split("\n"):
                        calls_section += f"       {line}\n"
            else:
                calls_section += f"\n  [NO MATCH] {cal_entry}\n"
                calls_section += "       (No matching Salesforce opportunity found)\n"

    sections.append(calls_section)

    # ── Follow-ups Due ──
    followups = _collect_all_followups(opportunities, today)
    followup_section = f"""
FOLLOW-UPS DUE
{LINE}"""
    if followups:
        for item in followups:
            followup_section += f"\n  - {item}"
    else:
        followup_section += "\n  No overdue follow-ups found."

    sections.append(followup_section)

    # ── At-Risk Deals ──
    at_risk = [o for o in opportunities if o.is_at_risk]
    at_risk.sort(key=lambda o: o.days_since_last_activity or 0, reverse=True)

    risk_section = f"""
AT-RISK DEALS (5+ days no activity)
{LINE}"""

    if at_risk:
        for opp in at_risk:
            last_type = "Meeting" if opp.avoma_meetings else "Unknown"
            risk_section += (
                f"\n  - {opp.account_name} ({opp.stage}, {_fmt_amount(opp.amount)})"
                f"\n    {opp.days_since_last_activity} days since last activity | "
                f"Last type: {last_type} | Closes: {_fmt_date(opp.close_date)}"
            )
            if opp.next_step:
                risk_section += f"\n    SF Next Step: {opp.next_step}"

        if risk_analysis:
            risk_section += f"\n\n  --- AI Risk Analysis ---"
            for line in risk_analysis.strip().split("\n"):
                risk_section += f"\n  {line}"
    else:
        risk_section += "\n  All deals have recent activity. Pipeline looks healthy!"

    sections.append(risk_section)

    # ── Priority Focus ──
    priority_section = f"""
PRIORITY FOCUS
{LINE}"""
    if priority_analysis:
        for line in priority_analysis.strip().split("\n"):
            priority_section += f"\n  {line}"
    else:
        # Fallback: simple ranking by urgency score
        scored = _rank_opportunities(opportunities)
        for i, (opp, reason) in enumerate(scored[:3], 1):
            priority_section += (
                f"\n  {i}. {opp.account_name} ({_fmt_amount(opp.amount)}, "
                f"closes {_fmt_date(opp.close_date)}): {reason}"
            )

    sections.append(priority_section)

    # ── Footer ──
    sections.append(f"""
{DOUBLE_LINE}
  Generated at {today.strftime('%Y-%m-%d')} | Data: Salesforce + Avoma + Local
{DOUBLE_LINE}
""")

    return "\n".join(sections)


def _format_last_meeting(meeting: AvomaMeeting) -> str:
    """Format a compact summary of the last Avoma meeting."""
    date_str = meeting.meeting_date.strftime("%m/%d")
    parts = f"       Last conversation ({date_str}): "

    if meeting.summary:
        # Truncate summary to ~200 chars
        summary = meeting.summary[:200]
        if len(meeting.summary) > 200:
            summary += "..."
        parts += summary
    elif meeting.key_topics:
        parts += "Topics: " + ", ".join(meeting.key_topics[:4])
    else:
        parts += meeting.title

    parts += "\n"
    return parts


def _collect_pending_actions(meetings: list[AvomaMeeting]) -> list[str]:
    """Collect incomplete action items from recent meetings."""
    pending = []
    for m in meetings[:3]:  # Last 3 meetings
        for ai in m.action_items:
            if not ai.completed:
                item = ai.text
                if ai.due_date:
                    item += f" (due {ai.due_date.strftime('%m/%d')})"
                if ai.assignee:
                    item += f" [{ai.assignee}]"
                pending.append(item)
    return pending


def _collect_all_followups(opportunities: list[Opportunity], today: date) -> list[str]:
    """Collect all due/overdue follow-ups across the pipeline."""
    items = []

    for opp in opportunities:
        # Check Salesforce Next Steps
        if opp.next_step:
            items.append(f"{opp.account_name}: {opp.next_step} (SF Next Step)")

        # Check Avoma action items
        for m in opp.avoma_meetings[:2]:
            for ai in m.action_items:
                if ai.completed:
                    continue
                if ai.due_date and ai.due_date <= today:
                    days_overdue = (today - ai.due_date).days
                    overdue_str = f" (overdue {days_overdue} days)" if days_overdue > 0 else " (due today)"
                    items.append(f"{opp.account_name}: {ai.text}{overdue_str}")

    return items


def _rank_opportunities(opportunities: list[Opportunity]) -> list[tuple[Opportunity, str]]:
    """Simple urgency ranking when AI analysis is unavailable."""
    today = date.today()
    scored: list[tuple[float, Opportunity, str]] = []

    for opp in opportunities:
        score = 0.0
        reason_parts = []

        # Deal size weight
        score += opp.amount / 100_000

        # Close date urgency
        if opp.close_date:
            days_to_close = (opp.close_date - today).days
            if days_to_close <= 7:
                score += 30
                reason_parts.append("closing this week")
            elif days_to_close <= 14:
                score += 20
                reason_parts.append("closing in 2 weeks")
            elif days_to_close <= 30:
                score += 10
                reason_parts.append("closing this month")

        # Staleness penalty/urgency
        if opp.days_since_last_activity and opp.days_since_last_activity >= 5:
            score += opp.days_since_last_activity * 2
            reason_parts.append(f"{opp.days_since_last_activity}d since last touch")

        # Stage advancement opportunity
        if opp.stage in ("Proposal", "Negotiation"):
            score += 15
            reason_parts.append(f"in {opp.stage}")

        reason = ", ".join(reason_parts) if reason_parts else "active deal"
        scored.append((score, opp, reason))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [(opp, reason) for _, opp, reason in scored]
