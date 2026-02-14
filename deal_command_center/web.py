"""Flask web server for the Deal Command Center dashboard."""

import json
import logging
import os
import threading
from datetime import date, datetime
from pathlib import Path

from flask import Flask, jsonify, render_template, request

from .brief import generate_brief
from .credentials import load_credentials, credentials_complete, ENV_PATH
from .pipeline import PipelineResult, run_pipeline

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
OUTPUT_DIR = BASE_DIR / "output"

app = Flask(
    __name__,
    template_folder=str(TEMPLATE_DIR),
    static_folder=str(STATIC_DIR),
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "deal-command-center-dev-key")

# In-memory store for the latest brief (simple single-user tool)
_state = {
    "latest_result": None,
    "latest_brief": None,
    "generated_at": None,
    "is_generating": False,
    "progress": [],
}
_lock = threading.Lock()


def _serialize_opportunity(opp) -> dict:
    """Convert an Opportunity dataclass to a JSON-safe dict."""
    return {
        "id": opp.id,
        "name": opp.name,
        "account_name": opp.account_name,
        "stage": opp.stage,
        "close_date": opp.close_date.isoformat() if opp.close_date else None,
        "amount": opp.amount,
        "last_activity_date": opp.last_activity_date.isoformat() if opp.last_activity_date else None,
        "next_step": opp.next_step,
        "days_since_last_activity": opp.days_since_last_activity,
        "is_at_risk": opp.is_at_risk,
        "closes_this_month": opp.closes_this_month,
        "meeting_count": len(opp.avoma_meetings),
        "has_local_context": bool(opp.local_context),
        "last_meeting_summary": (
            opp.avoma_meetings[0].summary[:200] if opp.avoma_meetings and opp.avoma_meetings[0].summary
            else None
        ),
        "last_meeting_date": (
            opp.avoma_meetings[0].meeting_date.isoformat() if opp.avoma_meetings else None
        ),
        "pending_actions": [
            ai.text for m in opp.avoma_meetings[:2]
            for ai in m.action_items if not ai.completed
        ][:5],
    }


def _serialize_result(result: PipelineResult) -> dict:
    """Convert a PipelineResult to a JSON-safe dict."""
    opps = result.opportunities
    at_risk = [o for o in opps if o.is_at_risk]
    total_pipeline = sum(o.amount for o in opps)
    closing_month = [o for o in opps if o.closes_this_month]

    return {
        "summary": {
            "total_pipeline": total_pipeline,
            "deal_count": len(opps),
            "closing_this_month_value": sum(o.amount for o in closing_month),
            "closing_this_month_count": len(closing_month),
            "at_risk_count": len(at_risk),
        },
        "opportunities": [_serialize_opportunity(o) for o in opps],
        "calendar_matches": [
            {
                "entry": cal,
                "matched": _serialize_opportunity(opp) if opp else None,
                "prep": result.call_preps.get(opp.account_name) if opp else None,
            }
            for cal, opp in result.calendar_matches
        ],
        "at_risk": [_serialize_opportunity(o) for o in at_risk],
        "risk_analysis": result.risk_analysis,
        "priority_analysis": result.priority_analysis,
        "errors": result.errors,
    }


@app.route("/")
def index():
    """Main dashboard page."""
    creds = load_credentials()
    has_creds = credentials_complete(creds)
    return render_template(
        "dashboard.html",
        has_creds=has_creds,
        state=_state,
        today=date.today().strftime("%A, %B %d, %Y"),
    )


@app.route("/api/generate", methods=["POST"])
def api_generate():
    """Trigger brief generation. Accepts optional calendar_text and skip_ai."""
    with _lock:
        if _state["is_generating"]:
            return jsonify({"status": "already_running"}), 409

    data = request.get_json(silent=True) or {}
    calendar_text = data.get("calendar_text", "")
    skip_ai = data.get("skip_ai", False)

    def _generate():
        with _lock:
            _state["is_generating"] = True
            _state["progress"] = ["Starting pipeline..."]

        try:
            creds = load_credentials()
            result = run_pipeline(
                calendar_text=calendar_text,
                skip_ai=skip_ai,
                creds=creds,
            )

            brief_text = generate_brief(
                opportunities=result.opportunities,
                calendar_matches=result.calendar_matches,
                call_preps=result.call_preps,
                risk_analysis=result.risk_analysis,
                priority_analysis=result.priority_analysis,
            )

            # Save to file
            OUTPUT_DIR.mkdir(exist_ok=True)
            output_file = OUTPUT_DIR / f"brief_{date.today().isoformat()}.txt"
            output_file.write_text(brief_text)

            with _lock:
                _state["latest_result"] = _serialize_result(result)
                _state["latest_brief"] = brief_text
                _state["generated_at"] = datetime.now().isoformat()
                _state["is_generating"] = False
                _state["progress"].append("Done!")

        except Exception as exc:
            logger.exception("Pipeline error")
            with _lock:
                _state["is_generating"] = False
                _state["progress"].append(f"Error: {exc}")

    thread = threading.Thread(target=_generate, daemon=True)
    thread.start()

    return jsonify({"status": "started"})


@app.route("/api/status")
def api_status():
    """Check generation status and get latest results."""
    with _lock:
        return jsonify({
            "is_generating": _state["is_generating"],
            "generated_at": _state["generated_at"],
            "has_data": _state["latest_result"] is not None,
            "progress": _state["progress"],
        })


@app.route("/api/brief")
def api_brief():
    """Get the latest brief data."""
    with _lock:
        if _state["latest_result"] is None:
            return jsonify({"error": "No brief generated yet"}), 404
        return jsonify({
            "data": _state["latest_result"],
            "text": _state["latest_brief"],
            "generated_at": _state["generated_at"],
        })


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    """Get or update credentials."""
    if request.method == "GET":
        creds = load_credentials()
        # Mask sensitive values
        masked = {}
        for key, val in creds.items():
            if val:
                masked[key] = val[:3] + "*" * min(len(val) - 3, 20) if len(val) > 3 else "***"
            else:
                masked[key] = ""
        return jsonify(masked)

    # POST - update credentials
    data = request.get_json(silent=True) or {}
    existing_lines = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                existing_lines[k] = line

    changed = False
    for key, value in data.items():
        if value and not value.endswith("*"):  # Don't save masked values
            existing_lines[key] = f"{key}={value}"
            changed = True

    if changed:
        lines = [v for v in existing_lines.values()]
        ENV_PATH.write_text("\n".join(lines) + "\n")

    return jsonify({"status": "saved"})


def create_app():
    """Application factory for gunicorn/production use."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return app


def run_server(host: str = "0.0.0.0", port: int = 5000, debug: bool = False):
    """Run the Flask development server."""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    TEMPLATE_DIR.mkdir(exist_ok=True)
    STATIC_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"\n  Deal Command Center running at http://{host}:{port}")
    print(f"  Press Ctrl+C to stop.\n")
    app.run(host=host, port=port, debug=debug)
