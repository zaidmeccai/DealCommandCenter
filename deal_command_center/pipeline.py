"""Pipeline runner - shared orchestration logic used by both CLI and web server."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from .analyzer import DealAnalyzer
from .avoma_client import AvomaClient
from .calendar_parser import CalendarEntry, match_calendar_to_accounts, parse_calendar_input
from .credentials import load_credentials
from .local_deals import read_deal_folders
from .matcher import match_local_deals_to_opportunities, match_meetings_to_opportunities
from .salesforce_client import Opportunity, SalesforceClient

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """All data produced by a single pipeline run."""
    opportunities: list[Opportunity] = field(default_factory=list)
    calendar_matches: list[tuple[str, "Opportunity | None"]] = field(default_factory=list)
    call_preps: dict[str, str] = field(default_factory=dict)
    risk_analysis: str = ""
    priority_analysis: str = ""
    errors: list[str] = field(default_factory=list)
    steps_completed: list[str] = field(default_factory=list)


def fetch_salesforce_data(creds: dict[str, str]) -> tuple[list[Opportunity], str | None]:
    """Connect to Salesforce and fetch pipeline. Returns (opps, error_or_none)."""
    sf_user = creds.get("SALESFORCE_USERNAME", "")
    sf_pass = creds.get("SALESFORCE_PASSWORD", "")
    sf_token = creds.get("SALESFORCE_SECURITY_TOKEN", "")
    sf_email = creds.get("MY_SALESFORCE_EMAIL", "") or sf_user
    sf_domain = os.getenv("SALESFORCE_DOMAIN", "login")

    if not all([sf_user, sf_pass, sf_token]):
        return [], "Salesforce credentials incomplete"

    client = SalesforceClient(sf_user, sf_pass, sf_token, domain=sf_domain)
    if not client.connect():
        return [], "Salesforce authentication failed"

    opps = client.get_my_opportunities(sf_email)
    return opps, None


def fetch_avoma_data(creds: dict[str, str]) -> tuple[list, str | None]:
    """Connect to Avoma and fetch recent meetings. Returns (meetings, error_or_none)."""
    api_key = creds.get("AVOMA_API_KEY", "")
    if not api_key:
        return [], "Avoma API key not set"

    client = AvomaClient(api_key)
    meetings = client.get_recent_meetings(days=30)
    return meetings, None


def run_pipeline(
    calendar_text: str = "",
    skip_ai: bool = False,
    creds: dict[str, str] | None = None,
) -> PipelineResult:
    """Run the full pipeline and return structured results.

    This is the shared entry point for both CLI and web server.
    """
    result = PipelineResult()

    # Step 1: Credentials
    if creds is None:
        creds = load_credentials()
    result.steps_completed.append("credentials")

    # Step 2: Fetch Salesforce
    opportunities, sf_err = fetch_salesforce_data(creds)
    if sf_err:
        result.errors.append(f"Salesforce: {sf_err}")
    result.opportunities = opportunities
    result.steps_completed.append("salesforce")

    # Step 3: Fetch Avoma
    meetings, av_err = fetch_avoma_data(creds)
    if av_err:
        result.errors.append(f"Avoma: {av_err}")
    result.steps_completed.append("avoma")

    # Step 4: Match data
    if opportunities and meetings:
        opportunities = match_meetings_to_opportunities(opportunities, meetings)

    local_deals = read_deal_folders()
    if local_deals and opportunities:
        opportunities = match_local_deals_to_opportunities(opportunities, local_deals)
    result.opportunities = opportunities
    result.steps_completed.append("matching")

    # Step 5: Calendar
    if calendar_text.strip():
        cal_entries = parse_calendar_input(calendar_text)
        if cal_entries:
            account_names = [o.account_name for o in opportunities]
            raw_matches = match_calendar_to_accounts(cal_entries, account_names)
            for display, matched_account in raw_matches:
                matched_opp = None
                if matched_account:
                    matched_opp = next(
                        (o for o in opportunities if o.account_name == matched_account), None
                    )
                result.calendar_matches.append((display, matched_opp))
    result.steps_completed.append("calendar")

    # Step 6: AI Analysis
    if not skip_ai:
        anthropic_key = creds.get("ANTHROPIC_API_KEY", "")
        if not anthropic_key:
            result.errors.append("Anthropic API key not set, skipping AI analysis")
            skip_ai = True

    if not skip_ai:
        analyzer = DealAnalyzer(anthropic_key)

        # Call preps
        calls_with_opps = [(cal, opp) for cal, opp in result.calendar_matches if opp is not None]
        for cal_entry, opp in calls_with_opps:
            prep = analyzer.generate_call_prep(opp, calendar_entry=cal_entry)
            result.call_preps[opp.account_name] = prep

        # Risk analysis
        at_risk = [o for o in opportunities if o.is_at_risk]
        if at_risk:
            result.risk_analysis = analyzer.generate_risk_assessment(at_risk)

        # Priority analysis
        if opportunities:
            result.priority_analysis = analyzer.generate_priority_recommendations(opportunities)

    result.steps_completed.append("analysis")
    return result
