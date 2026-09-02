"""
Flask Web Dashboard for the USCIS Case Status Tracker.

Serves a premium local dashboard and exposes API endpoints for
triggering checks, login, and fetching status.
"""

import logging
from datetime import datetime

from flask import Flask, render_template, jsonify, request

import config
import scheduler as sched_module
import silent_update_detector

logger = logging.getLogger(__name__)

app = Flask(
    __name__,
    static_folder="static",
    template_folder="templates",
)


# ─────────────────────────────────────────────────────────
# Template Filters
# ─────────────────────────────────────────────────────────
@app.template_filter("format_datetime")
def format_datetime_filter(value):
    """Format an ISO datetime string for display."""
    if not value or value == "Never":
        return "Never"
    try:
        if isinstance(value, str):
            # Handle various ISO formats
            value = value.replace("Z", "+00:00")
            dt = datetime.fromisoformat(value)
        elif isinstance(value, datetime):
            dt = value
        else:
            return str(value)
        return dt.strftime("%b %d, %Y  %I:%M %p")
    except (ValueError, TypeError):
        return str(value)


# ─────────────────────────────────────────────────────────
# In-Memory Authentic Live Session Store
# NEVER pre-loaded from disk or .env variables!
# ─────────────────────────────────────────────────────────
_session_cases = {}
_session_last_checked = None


# ─────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────
@app.route("/")
def index():
    """
    Render the main dashboard.
    Starts completely RAW / EMPTY — never loads previous session or .env data.
    """
    from case_fetcher import EVENT_CODE_DESCRIPTIONS

    # Aggregate stats only from the current live session
    all_changes = []
    silent_count = 0
    total_events = 0

    for receipt, data in _session_cases.items():
        changes = data.get("change_log", [])
        all_changes.extend([{**c, "receipt_number": receipt} for c in changes])
        silent_count += sum(1 for c in changes if c.get("type") == "silent_timestamp_update")
        total_events += len(data.get("event_history", []))

    return render_template(
        "dashboard.html",
        cases=_session_cases,
        last_checked=_session_last_checked,
        all_changes=all_changes,
        silent_update_count=silent_count,
        total_event_count=total_events,
        event_codes=EVENT_CODE_DESCRIPTIONS,
    )


@app.route("/api/fetch-live", methods=["POST"])
def api_fetch_live():
    """
    Fetch authentic, real-time live case data directly from myUSCIS internal API.
    Takes receipt_numbers and cookie from the request.
    """
    global _session_last_checked
    import re
    from case_fetcher import fetch_case_from_myuscis_with_cookie
    import silent_update_detector

    try:
        data = request.get_json(force=True) or {}
        raw_receipts = data.get("receipt_numbers", "").strip()
        raw_cookie = data.get("cookie", "").strip()

        if not raw_receipts:
            return jsonify({"success": False, "error": "Please enter at least one USCIS receipt number."}), 400
        if not raw_cookie:
            return jsonify({"success": False, "error": "Please enter your myUSCIS session cookie."}), 400

        # Parse receipt numbers
        receipt_list = [r.upper() for r in re.findall(r"[A-Z]{3}\d{10}", raw_receipts.upper())]
        if not receipt_list:
            receipt_list = [r.strip().upper() for r in raw_receipts.replace(",", " ").split() if r.strip()]

        # Parse cookie string into dict
        cookies_dict = {}
        if "_myuscis_session_rx=" in raw_cookie or ";" in raw_cookie:
            for part in raw_cookie.split(";"):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    cookies_dict[k.strip()] = v.strip()
        else:
            cookies_dict["_myuscis_session_rx"] = raw_cookie

        # Also save cookies locally for convenience
        cookies_list = [{"name": k, "value": v} for k, v in cookies_dict.items()]
        import auth
        auth.save_cookies(cookies_list)

        results = {}
        errors = {}

        for rn in receipt_list:
            case_data = fetch_case_from_myuscis_with_cookie(rn, cookies_dict)
            if case_data:
                # Detect any changes
                changes = silent_update_detector.detect_changes(rn, case_data)
                results[rn] = {
                    "current_status": case_data.get("status_text", ""),
                    "form_type": case_data.get("form_type", ""),
                    "form_name": case_data.get("form_name", ""),
                    "applicant_name": case_data.get("applicant_name", ""),
                    "submission_date": case_data.get("submission_date", ""),
                    "last_updated_at": case_data.get("last_updated_at", ""),
                    "latest_event_code": case_data.get("latest_event_code", ""),
                    "service_center": case_data.get("service_center", ""),
                    "closed": case_data.get("closed", False),
                    "action_required": case_data.get("action_required", False),
                    "event_history": case_data.get("event_history", []),
                    "documents": case_data.get("documents", []),
                    "notices": case_data.get("notices", []),
                    "change_log": changes,
                    "snapshots": [case_data],
                }
            else:
                errors[rn] = "myUSCIS API returned 401 Unauthorized or case not found. Check session cookie."

        if not results:
            return jsonify({
                "success": False,
                "error": "Failed to fetch any cases from myUSCIS. Please verify your _myuscis_session_rx cookie.",
                "errors": errors,
            }), 401

        _session_cases.clear()
        _session_cases.update(results)
        _session_last_checked = datetime.now().isoformat()

        return jsonify({
            "success": True,
            "cases": _session_cases,
            "count": len(_session_cases),
            "errors": errors,
            "last_checked": _session_last_checked,
        })

    except Exception as e:
        logger.error("Live fetch failed: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/clear-session", methods=["POST"])
def api_clear_session():
    """Clear in-memory session results (resets dashboard to raw/empty)."""
    global _session_last_checked
    _session_cases.clear()
    _session_last_checked = None
    import auth
    auth.clear_cookies()
    return jsonify({"success": True, "message": "Session reset to raw/empty."})


@app.route("/api/status")
def api_status():
    """Return current session status as JSON."""
    cases_summary = {}
    for receipt, data in _session_cases.items():
        cases_summary[receipt] = {
            "current_status": data.get("current_status", ""),
            "change_count": len(data.get("change_log", [])),
            "event_count": len(data.get("event_history", [])),
        }

    return jsonify({
        "cases_count": len(_session_cases),
        "last_checked": _session_last_checked,
        "cases": cases_summary,
    })


# ─────────────────────────────────────────────────────────
# Start the dashboard
# ─────────────────────────────────────────────────────────
def run_dashboard():
    """Start the Flask dashboard server."""
    logger.info(
        "Starting dashboard at http://%s:%d",
        config.DASHBOARD_HOST,
        config.DASHBOARD_PORT,
    )
    app.run(
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        debug=False,
        use_reloader=False,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_dashboard()
