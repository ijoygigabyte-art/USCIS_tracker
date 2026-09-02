"""
Scheduler module.

Periodically runs the fetch → detect → notify pipeline at a configurable interval.
Can run standalone or be started as a background thread alongside the dashboard.
"""

import logging
import threading
import time
from datetime import datetime, timezone

import schedule

import config
import case_fetcher
import silent_update_detector
import notifier

logger = logging.getLogger(__name__)

# Track scheduler state
_scheduler_thread: threading.Thread | None = None
_scheduler_running = False
_last_run: str | None = None
_next_run: str | None = None
_check_lock = threading.Lock()


def run_check_cycle() -> list[dict]:
    """
    Execute one full check cycle:
      1. Fetch case data for all receipt numbers
      2. Detect changes against stored history
      3. Send notifications for any changes
    
    Returns a list of all changes detected across all cases.
    """
    global _last_run

    if not _check_lock.acquire(blocking=False):
        logger.warning("Check cycle already in progress. Ignoring concurrent request.")
        return []

    try:
        logger.info("=" * 50)
        logger.info("Starting check cycle at %s", datetime.now(timezone.utc).isoformat())
        logger.info("=" * 50)

        all_changes = []

        if not config.RECEIPT_NUMBERS:
            logger.warning(
                "No receipt numbers configured! "
                "Set USCIS_RECEIPT_NUMBERS in your .env file."
            )
            return all_changes

        for receipt_number in config.RECEIPT_NUMBERS:
            try:
                # 1. Fetch
                case_data = case_fetcher.fetch_case(receipt_number)
                if not case_data:
                    logger.error("Skipping %s — fetch failed.", receipt_number)
                    continue

                # 2. Detect
                changes = silent_update_detector.detect_changes(receipt_number, case_data, save_to_disk=True)

                # 3. Notify
                if changes:
                    notifier.notify_changes(receipt_number, changes)
                    all_changes.extend(changes)

            except Exception as e:
                logger.error("Error processing %s: %s", receipt_number, e, exc_info=True)

        _last_run = datetime.now(timezone.utc).isoformat()

        logger.info(
            "Check cycle complete. %d change(s) detected across %d case(s).",
            len(all_changes),
            len(config.RECEIPT_NUMBERS),
        )
        return all_changes
    finally:
        _check_lock.release()


def _scheduler_loop():
    """Internal loop that runs the scheduler."""
    global _scheduler_running, _next_run
    _scheduler_running = True

    # Schedule the job
    schedule.every(config.POLL_INTERVAL_HOURS).hours.do(run_check_cycle)
    _next_run = str(schedule.next_run())

    logger.info(
        "Scheduler started. Polling every %d hour(s). Next run: %s",
        config.POLL_INTERVAL_HOURS,
        _next_run,
    )

    while _scheduler_running:
        schedule.run_pending()
        _next_run = str(schedule.next_run()) if schedule.jobs else None
        time.sleep(30)  # Check every 30 seconds


def start_scheduler() -> None:
    """Start the polling scheduler in a background thread."""
    global _scheduler_thread
    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.info("Scheduler is already running.")
        return

    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()
    logger.info("Scheduler thread started.")


def stop_scheduler() -> None:
    """Stop the polling scheduler."""
    global _scheduler_running
    _scheduler_running = False
    schedule.clear()
    logger.info("Scheduler stopped.")


def get_scheduler_status() -> dict:
    """Get the current scheduler status for the dashboard."""
    return {
        "running": _scheduler_running,
        "poll_interval_hours": config.POLL_INTERVAL_HOURS,
        "last_run": _last_run,
        "next_run": _next_run,
        "tracked_cases": len(config.RECEIPT_NUMBERS),
    }
