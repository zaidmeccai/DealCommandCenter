"""Main CLI entry point - orchestrates the daily deal brief generation."""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .analyzer import DealAnalyzer
from .avoma_client import AvomaClient
from .brief import generate_brief
from .calendar_parser import CalendarEntry, match_calendar_to_accounts, parse_calendar_input
from .credentials import ensure_credentials
from .local_deals import read_deal_folders
from .matcher import match_local_deals_to_opportunities, match_meetings_to_opportunities
from .salesforce_client import Opportunity, SalesforceClient

logger = logging.getLogger(__name__)

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _prompt_calendar() -> list[CalendarEntry]:
    """Prompt user to paste their calendar for today."""
    print("\nPaste your calendar for today (meetings list).")
    print("Press Enter twice when done, or type 'skip' to skip:\n")

    lines: list[str] = []
    empty_count = 0
    try:
        while True:
            line = input()
            if line.strip().lower() == "skip":
                print("  Skipping calendar input.")
                return []
            if line.strip() == "":
                empty_count += 1
                if empty_count >= 2:
                    break
            else:
                empty_count = 0
            lines.append(line)
    except EOFError:
        pass

    text = "\n".join(lines).strip()
    if not text:
        return []

    entries = parse_calendar_input(text)
    print(f"  Parsed {len(entries)} calendar entries.")
    return entries


def _fetch_salesforce_data(creds: dict[str, str]) -> list[Opportunity]:
    """Connect to Salesforce and fetch pipeline."""
    sf_user = creds.get("SALESFORCE_USERNAME", "")
    sf_pass = creds.get("SALESFORCE_PASSWORD", "")
    sf_token = creds.get("SALESFORCE_SECURITY_TOKEN", "")
    sf_email = creds.get("MY_SALESFORCE_EMAIL", "") or sf_user
    sf_domain = os.getenv("SALESFORCE_DOMAIN", "login")

    if not all([sf_user, sf_pass, sf_token]):
        print("  [!] Salesforce credentials incomplete. Skipping SF data.")
        return []

    print("  Connecting to Salesforce...")
    client = SalesforceClient(sf_user, sf_pass, sf_token, domain=sf_domain)

    if not client.connect():
        print("  [!] Salesforce authentication failed. Check credentials in .env")
        return []

    print("  Fetching open opportunities...")
    opps = client.get_my_opportunities(sf_email)
    print(f"  Found {len(opps)} open opportunities.")
    return opps


def _fetch_avoma_data(creds: dict[str, str]):
    """Connect to Avoma and fetch recent meetings."""
    api_key = creds.get("AVOMA_API_KEY", "")
    if not api_key:
        print("  [!] Avoma API key not set. Skipping Avoma data.")
        return []

    print("  Connecting to Avoma...")
    client = AvomaClient(api_key)

    print("  Fetching recent meetings (last 30 days)...")
    meetings = client.get_recent_meetings(days=30)
    print(f"  Found {len(meetings)} meetings.")
    return meetings


def run(verbose: bool = False, skip_calendar: bool = False, skip_ai: bool = False) -> None:
    """Run the full daily brief generation pipeline."""
    setup_logging(verbose)

    print("\n" + "=" * 50)
    print("  DEAL COMMAND CENTER")
    print("  Generating your daily brief...")
    print("=" * 50)

    # ── Step 1: Credentials ──
    print("\n[1/6] Checking credentials...")
    creds = ensure_credentials()

    # ── Step 2: Fetch data ──
    print("\n[2/6] Fetching pipeline data...")
    opportunities = _fetch_salesforce_data(creds)
    meetings = _fetch_avoma_data(creds)

    if not opportunities:
        print("\n  No Salesforce opportunities found. The brief will be limited.")
        print("  Check your SALESFORCE_USERNAME and MY_SALESFORCE_EMAIL in .env\n")

    # ── Step 3: Match data ──
    print("\n[3/6] Matching data sources...")
    if opportunities and meetings:
        opportunities = match_meetings_to_opportunities(opportunities, meetings)
        matched_count = sum(1 for o in opportunities if o.avoma_meetings)
        print(f"  Matched Avoma meetings to {matched_count}/{len(opportunities)} opportunities.")

    local_deals = read_deal_folders()
    if local_deals:
        opportunities = match_local_deals_to_opportunities(opportunities, local_deals)
        local_matched = sum(1 for o in opportunities if o.local_context)
        print(f"  Matched local deal folders to {local_matched}/{len(opportunities)} opportunities.")

    # ── Step 4: Calendar ──
    print("\n[4/6] Calendar setup...")
    calendar_matches: list[tuple[str, Opportunity | None]] = []

    if not skip_calendar:
        cal_entries = _prompt_calendar()
        if cal_entries:
            account_names = [o.account_name for o in opportunities]
            raw_matches = match_calendar_to_accounts(cal_entries, account_names)

            for display, matched_account in raw_matches:
                matched_opp = None
                if matched_account:
                    matched_opp = next(
                        (o for o in opportunities if o.account_name == matched_account), None
                    )
                calendar_matches.append((display, matched_opp))

            matched_calls = sum(1 for _, o in calendar_matches if o is not None)
            print(f"  Matched {matched_calls}/{len(cal_entries)} calendar entries to deals.")
    else:
        print("  Calendar input skipped.")

    # ── Step 5: AI Analysis ──
    print("\n[5/6] Generating AI insights...")
    call_preps: dict[str, str] = {}
    risk_analysis = ""
    priority_analysis = ""

    if not skip_ai:
        anthropic_key = creds.get("ANTHROPIC_API_KEY", "")
        if not anthropic_key:
            print("  [!] Anthropic API key not set. Skipping AI analysis.")
            skip_ai = True

    if not skip_ai:
        analyzer = DealAnalyzer(anthropic_key)

        # Generate call preps for today's matched calls
        calls_with_opps = [(cal, opp) for cal, opp in calendar_matches if opp is not None]
        if calls_with_opps:
            print(f"  Generating call prep for {len(calls_with_opps)} calls...")
            for cal_entry, opp in calls_with_opps:
                prep = analyzer.generate_call_prep(opp, calendar_entry=cal_entry)
                call_preps[opp.account_name] = prep

        # Risk analysis
        at_risk = [o for o in opportunities if o.is_at_risk]
        if at_risk:
            print(f"  Analyzing {len(at_risk)} at-risk deals...")
            risk_analysis = analyzer.generate_risk_assessment(at_risk)

        # Priority recommendations
        if opportunities:
            print("  Generating priority recommendations...")
            priority_analysis = analyzer.generate_priority_recommendations(opportunities)
    else:
        print("  AI analysis skipped.")

    # ── Step 6: Generate Brief ──
    print("\n[6/6] Assembling your brief...\n")

    brief = generate_brief(
        opportunities=opportunities,
        calendar_matches=calendar_matches,
        call_preps=call_preps,
        risk_analysis=risk_analysis,
        priority_analysis=priority_analysis,
    )

    print(brief)

    # Save to file
    output_dir = Path(__file__).resolve().parent.parent / "output"
    output_dir.mkdir(exist_ok=True)
    from datetime import date as date_cls
    output_file = output_dir / f"brief_{date_cls.today().isoformat()}.txt"
    output_file.write_text(brief)
    print(f"\nBrief saved to: {output_file}")


def main() -> None:
    """CLI entry point with argument parsing."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Daily Deal Command Center - Generate your morning sales brief",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m deal_command_center                    # Full interactive run
  python -m deal_command_center --skip-calendar    # Skip calendar paste
  python -m deal_command_center --skip-ai          # Skip Claude AI analysis
  python -m deal_command_center --verbose          # Debug logging
  python -m deal_command_center --setup            # Re-run credential setup
        """,
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable debug logging"
    )
    parser.add_argument(
        "--skip-calendar", action="store_true", help="Skip calendar input prompt"
    )
    parser.add_argument(
        "--skip-ai", action="store_true", help="Skip Claude AI analysis (faster, no API cost)"
    )
    parser.add_argument(
        "--setup", action="store_true", help="Re-run credential setup"
    )
    parser.add_argument(
        "--clear-cache", action="store_true", help="Clear Avoma transcript cache"
    )
    parser.add_argument(
        "--web", action="store_true", help="Start web dashboard instead of CLI"
    )
    parser.add_argument(
        "--port", type=int, default=5000, help="Port for web dashboard (default: 5000)"
    )

    args = parser.parse_args()

    if args.clear_cache:
        from .avoma_client import AvomaClient
        client = AvomaClient("")
        count = client.clear_cache()
        print(f"Cleared {count} cached files.")
        return

    if args.setup:
        from .credentials import interactive_setup
        interactive_setup()
        print("\nSetup complete. Run again without --setup to generate your brief.")
        return

    if args.web:
        from .web import run_server
        run_server(port=args.port, debug=args.verbose)
        return

    try:
        run(
            verbose=args.verbose,
            skip_calendar=args.skip_calendar,
            skip_ai=args.skip_ai,
        )
    except KeyboardInterrupt:
        print("\n\nBrief generation cancelled.")
        sys.exit(0)
    except Exception as exc:
        logger.exception("Fatal error generating brief")
        print(f"\n[ERROR] {exc}")
        print("Run with --verbose for more details.")
        sys.exit(1)


if __name__ == "__main__":
    main()
