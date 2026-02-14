# Daily Deal Command Center

A sales pipeline management tool that generates morning briefs by pulling data from Salesforce, Avoma, and local deal folders, then using Claude AI to produce actionable insights. Available as both a CLI tool and a web dashboard.

## What It Does

Run it each morning and get a scannable brief covering:

- **Pipeline Snapshot** - total value, deals closing this month/quarter, stage breakdown
- **Today's Calls** - pre-call intel matched from your calendar, with AI-generated talking points
- **Follow-ups Due** - overdue action items from Avoma and Salesforce next steps
- **At-Risk Deals** - opportunities with 5+ days of inactivity, with suggested re-engagement
- **Priority Focus** - AI-ranked top 2-3 deals to focus on today

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Option 1: Start the web dashboard
./start.sh web

# Option 2: Run from CLI
./start.sh cli

# Option 3: Run with Docker
./start.sh docker
```

Then open **http://localhost:5000** in your browser.

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure credentials

**Web:** Click "Settings" in the dashboard to enter credentials.

**CLI:** Run the setup wizard:

```bash
python -m deal_command_center --setup
```

**Manual:** Copy `.env.example` to `.env` and fill in:

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

### Web Dashboard

```bash
# Start the web server
python run_web.py

# Or via the CLI module
python -m deal_command_center --web

# Custom port
python run_web.py --port 8080

# Debug mode
python run_web.py --debug
```

Open http://localhost:5000, paste your calendar, click "Generate Morning Brief".

### CLI

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
```

### start.sh

```bash
./start.sh web [port]   # Start web dashboard (default: port 5000)
./start.sh cli [args]   # Run CLI tool with optional args
./start.sh docker       # Start with Docker Compose
./start.sh stop         # Stop Docker containers
./start.sh setup        # Install deps and configure credentials
```

## Hosting

### Docker (recommended for always-on)

```bash
# Create your .env file first
cp .env.example .env
# Edit .env with your credentials

# Build and start
docker compose up -d

# Check logs
docker compose logs -f

# Stop
docker compose down
```

The container exposes port 5000 and mounts your `.env`, `deals/`, `output/`, and `avoma_cache/` directories.

### Systemd (Linux server)

For running on a dedicated Linux server:

```bash
# Install to /opt
sudo mkdir -p /opt/deal-command-center
sudo cp -r . /opt/deal-command-center/
cd /opt/deal-command-center

# Create venv and install
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Copy and enable service
sudo cp deal-command-center.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now deal-command-center

# Check status
sudo systemctl status deal-command-center
```

### Reverse Proxy (nginx)

To put behind nginx with HTTPS:

```nginx
server {
    listen 443 ssl;
    server_name deals.yourcompany.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

### Cloud Hosting

**Railway / Render / Fly.io:**
1. Push this repo to GitHub
2. Connect your repo to the platform
3. Set environment variables (from `.env.example`) in the platform dashboard
4. Deploy - the `Dockerfile` will be auto-detected

**Procfile** (for Heroku-style platforms):
```
web: gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 "deal_command_center.web:create_app()"
```

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
  pipeline.py          # Shared orchestration (CLI + web)
  brief.py             # Text brief formatting
  web.py               # Flask web dashboard + API
  main.py              # CLI entry point

templates/
  dashboard.html       # Web dashboard UI

Dockerfile             # Container build
docker-compose.yml     # One-command hosting
start.sh               # Quick start script
deal-command-center.service  # Systemd unit file
```

## API Endpoints

The web server exposes these JSON endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard UI |
| `/api/generate` | POST | Trigger brief generation (`{calendar_text, skip_ai}`) |
| `/api/status` | GET | Check generation progress |
| `/api/brief` | GET | Get latest brief data + text |
| `/api/settings` | GET/POST | Read/update credentials |

## Notes

- Avoma transcripts are cached locally for 12 hours to avoid redundant API calls
- All API calls include retry logic with exponential backoff for rate limits
- If any data source is unavailable, the tool degrades gracefully and generates what it can
- The Claude model used for analysis is `claude-sonnet-4-20250514` (configurable in `analyzer.py`)
- The web dashboard is designed for single-user use (no auth) - add nginx basic auth or a VPN if hosting publicly
