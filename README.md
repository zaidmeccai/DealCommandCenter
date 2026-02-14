# Daily Deal Command Center

A CLI tool that generates a morning sales brief by pulling data from Salesforce, Avoma, and local deal folders, then using Claude AI to produce actionable insights.

## What It Does

Run it each morning and get a scannable brief covering:

- **Pipeline Snapshot** - total value, deals closing this month/quarter, stage breakdown
- **Today's Calls** - pre-call intel matched from your calendar, with AI-generated talking points
- **Follow-ups Due** - overdue action items from Avoma and Salesforce next steps
- **At-Risk Deals** - opportunities with 5+ days of inactivity, with suggested re-engagement
- **Priority Focus** - AI-ranked top 2-3 deals to focus on today

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

Run the setup wizard (prompts for each credential interactively):

```bash
python -m deal_command_center --setup
```

Or copy `.env.example` to `.env` and fill in manually:

```bash
cp .env.example .env
```

You'll need:
- **Salesforce**: username, password, security token
- **Avoma**: API key (from Avoma Settings > Integrations)
- **Anthropic**: Claude API key

### 3. Add local deal context (optional)

Add files to `deals/<account-name>/` for supplemental context:

```
deals/
  carmax/
    rfp-notes.txt
    competitive-intel.txt
  goodleap/
    rfp-notes.txt
```

These get matched to Salesforce opportunities by account name and included in AI analysis.

## Usage

```bash
# Full interactive run (will prompt for calendar paste)
python -m deal_command_center

# Skip calendar input
python -m deal_command_center --skip-calendar

# Skip AI analysis (faster, no Anthropic API cost)
python -m deal_command_center --skip-ai

# Debug logging
python -m deal_command_center --verbose

# Clear Avoma cache
python -m deal_command_center --clear-cache

# Or use the convenience script
python run.py
```

### Calendar Input

When prompted, paste your calendar for today. Supports common formats:

```
10:00 AM - CarMax Technical Review
11:30 AM - GoodLeap Follow-up Call
2:00 PM - Internal Pipeline Review
3:30 PM - Harvey Executive Briefing
```

Type `skip` to skip, or press Enter twice when done.

## Output

Briefs are printed to the terminal and saved to `output/brief_YYYY-MM-DD.txt`.

## Architecture

```
deal_command_center/
  credentials.py      # Secure .env credential management
  salesforce_client.py # Salesforce REST API integration
  avoma_client.py      # Avoma API with local caching
  local_deals.py       # Local deal folder reader
  matcher.py           # Cross-source data matching engine
  calendar_parser.py   # Calendar text parser
  analyzer.py          # Claude AI analysis engine
  brief.py             # Brief formatting and output
  main.py              # CLI orchestrator
```

## Notes

- Avoma transcripts are cached locally for 12 hours to avoid redundant API calls
- All API calls include retry logic with exponential backoff for rate limits
- If any data source is unavailable, the tool degrades gracefully and generates what it can
- The Claude model used for analysis is `claude-sonnet-4-20250514` (configurable in `analyzer.py`)
