"""
USCIS Case Status Tracker — Main Entry Point

Usage:
    python main.py                  # Start dashboard + scheduler
    python main.py --check          # Run a single check cycle and exit
    python main.py --login          # Trigger myUSCIS login only
    python main.py --dashboard      # Start dashboard only (no scheduler)
"""

import sys
import logging
import argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import config
import scheduler
import dashboard

# ─────────────────────────────────────────────────────────
# Logging Setup
# ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.DATA_DIR / "tracker.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("uscis_tracker")


def print_banner():
    """Print a startup banner."""
    host = config.DASHBOARD_HOST
    port = config.DASHBOARD_PORT
    interval = config.POLL_INTERVAL_HOURS
    cases = len(config.RECEIPT_NUMBERS)
    print("")
    print("=" * 58)
    print("  USCIS Case Status Tracker")
    print("  Silent Update Detection & Premium Dashboard")
    print("=" * 58)
    print(f"  Dashboard:  http://{host}:{port}")
    print(f"  Polling:    Every {interval} hour(s)")
    print(f"  Cases:      {cases} receipt number(s) configured")
    print("=" * 58)
    print("")


def main():
    parser = argparse.ArgumentParser(
        description="USCIS Case Status Tracker with Silent Update Detection"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run a single check cycle and exit",
    )
    parser.add_argument(
        "--login",
        action="store_true",
        help="Open browser for myUSCIS login only",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Start dashboard only (no scheduler)",
    )
    args = parser.parse_args()

    # ── Single check mode ──
    if args.check:
        logger.info("Running single check cycle...")
        changes = scheduler.run_check_cycle()
        if changes:
            print(f"\n[!] {len(changes)} change(s) detected:")
            for ch in changes:
                icon = {"alert": "[!!]", "warning": "[!]", "info": "[i]"}.get(
                    ch.get("severity", ""), "[*]"
                )
                print(f"  {icon} {ch['description']}")
        else:
            print("\n[OK] No changes detected.")
        return

    # ── Login only mode ──
    if args.login:
        import auth
        auth.login_and_capture_cookies()
        return

    # ── Dashboard + Scheduler ──
    print_banner()

    if not config.RECEIPT_NUMBERS:
        logger.warning(
            "No receipt numbers configured! "
            "Copy .env.example to .env and set USCIS_RECEIPT_NUMBERS"
        )
        print("  [!] No receipt numbers configured.")
        print("  Copy .env.example to .env and add your receipt number(s).\n")

    # Start the dashboard (blocks)
    dashboard.run_dashboard()


if __name__ == "__main__":
    main()
