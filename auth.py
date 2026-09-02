"""
Authentication module for myUSCIS.

Opens a real Chrome browser window so the user can log in manually.
After login, session cookies are captured and encrypted locally for
reuse by the case fetcher.
"""

import json
import time
import logging
import threading
from pathlib import Path

from cryptography.fernet import Fernet

import config

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """Create a Fernet cipher using the stored/generated key."""
    return Fernet(config.get_encryption_key())


def save_cookies(cookies: list[dict]) -> None:
    """Encrypt and save cookies to disk."""
    fernet = _get_fernet()
    raw = json.dumps(cookies).encode("utf-8")
    encrypted = fernet.encrypt(raw)
    config.COOKIES_FILE.write_bytes(encrypted)
    logger.info("Session cookies saved (encrypted).")


def load_cookies() -> list[dict] | None:
    """Load and decrypt cookies from disk. Returns None if absent/corrupt."""
    if not config.COOKIES_FILE.exists():
        return None
    try:
        fernet = _get_fernet()
        encrypted = config.COOKIES_FILE.read_bytes()
        raw = fernet.decrypt(encrypted)
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        logger.warning("Could not load saved cookies: %s", e)
        return None


def cookies_to_session_dict(cookies: list[dict]) -> dict:
    """Convert Selenium cookie list to a {name: value} dict for requests."""
    return {c["name"]: c["value"] for c in cookies}


_login_lock = threading.Lock()


def login_and_capture_cookies(timeout_seconds: int = 600) -> list[dict]:
    """
    Open a Chrome window, navigate to myUSCIS, wait for the user to log in,
    then capture the authenticated session cookies.
    
    Supports:
      1. In-browser floating button ('I am Logged In')
      2. Auto-detection of myUSCIS account dashboard (sign-out link or account page)
      3. Console ENTER key (non-blocking on Windows)
      4. Window close after logging in
    """
    import sys

    with _login_lock:
        # Check if another thread already captured cookies
        existing = load_cookies()
        if existing:
            logger.info("Valid cookies already available.")
            return existing

        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
        except ImportError:
            logger.error("Selenium not installed in this environment. Please paste cookies directly into the dashboard.")
            return []

        logger.info("Opening Chrome for myUSCIS login...")

        options = Options()
        options.add_argument("--start-maximized")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        driver = webdriver.Chrome(options=options)

        try:
            try:
                from selenium_stealth import stealth
                stealth(
                    driver,
                    languages=["en-US", "en"],
                    vendor="Google Inc.",
                    platform="Win32",
                    webgl_vendor="Intel Inc.",
                    renderer="Intel Iris OpenGL Engine",
                    fix_hairline=True,
                )
            except ImportError:
                logger.warning("selenium-stealth not installed. Bot detection may trigger.")

            driver.get(config.MYUSCIS_LOGIN_URL)

            print("\n" + "=" * 60)
            print("  USCIS LOGIN REQUIRED")
            print("=" * 60)
            print("  A Chrome browser window has opened.")
            print("  Please log in to your myUSCIS account.")
            print("  Once you see your account dashboard:")
            print("    * Click the floating 'I am Logged In' button in Chrome, OR")
            print("    * The tracker will auto-detect your login, OR")
            print("    * Press ENTER in this terminal.")
            print("=" * 60 + "\n")

            banner_js = """
            try {
                if (!document.getElementById('uscis-tracker-banner')) {
                    var b = document.createElement('div');
                    b.id = 'uscis-tracker-banner';
                    b.style.cssText = 'position:fixed;top:12px;right:16px;z-index:2147483647;' +
                                      'background:#0f172a;color:#f8fafc;padding:12px 18px;' +
                                      'border-radius:10px;box-shadow:0 10px 25px rgba(0,0,0,0.5);' +
                                      'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;' +
                                      'font-size:14px;display:flex;align-items:center;gap:12px;' +
                                      'border:2px solid #38bdf8;';
                    b.innerHTML = '<span style="font-weight:600;">📋 USCIS Tracker:</span>' +
                                  '<span>Log in, then click &rarr;</span>' +
                                  '<button id="uscis-finish-btn" style="background:#0284c7;color:#fff;' +
                                  'border:none;padding:8px 16px;border-radius:6px;cursor:pointer;' +
                                  'font-weight:700;font-size:13px;box-shadow:0 2px 6px rgba(0,0,0,0.3);">' +
                                  'I am Logged In</button>';
                    document.body.appendChild(b);
                    document.getElementById('uscis-finish-btn').onclick = function() {
                        window.__uscis_login_done = true;
                        this.innerText = 'Capturing session...';
                        this.style.background = '#16a34a';
                    };
                }
            } catch(e) {}
            """

            start_time = time.time()
            login_confirmed = False
            latest_cookies = []

            while time.time() - start_time < timeout_seconds:
                # Check if browser is still open
                try:
                    if not driver.window_handles:
                        logger.info("Chrome browser window was closed.")
                        break
                except Exception:
                    logger.info("Chrome browser window disconnected.")
                    break

                # Cache latest cookies
                try:
                    current_cookies = driver.get_cookies()
                    if current_cookies:
                        latest_cookies = current_cookies
                except Exception:
                    pass

                # 1. Inject the helper banner
                try:
                    driver.execute_script(banner_js)
                except Exception:
                    pass

                # 2. Check if user clicked the in-page button
                try:
                    is_clicked = driver.execute_script("return window.__uscis_login_done === true;")
                    if is_clicked:
                        logger.info("User clicked 'I am Logged In' button in browser.")
                        login_confirmed = True
                        break
                except Exception:
                    pass

                # 3. Auto-detection: check for sign-out elements or dashboard paths
                try:
                    curr_url = driver.current_url.lower()

                    # Definite proof of authentication: presence of a sign-out / log-out link
                    sign_out_elements = driver.find_elements(
                        By.XPATH,
                        "//a[contains(@href, 'sign_out') or contains(@href, 'logout') or contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'sign out')]"
                    )
                    if sign_out_elements:
                        logger.info("Auto-detected signed-in session via sign-out link.")
                        login_confirmed = True
                        break

                    # Path-based check: on an actual account page
                    not_homepage = curr_url.rstrip("/") not in [
                        "https://my.uscis.gov", "http://my.uscis.gov",
                        "https://myaccount.uscis.gov", "http://myaccount.uscis.gov"
                    ]
                    is_actual_account = (
                        ("/account" in curr_url and "need-an-account" not in curr_url)
                        or "/overview" in curr_url
                        or "/cases" in curr_url
                    )
                    is_not_login_page = not any(
                        kw in curr_url for kw in ["sign_in", "signin", "login", "need-an-account", "two_factor", "verify"]
                    )

                    if not_homepage and is_actual_account and is_not_login_page:
                        logger.info("Auto-detected myUSCIS account dashboard (URL: %s).", driver.current_url)
                        login_confirmed = True
                        break
                except Exception:
                    pass

                # 4. Check console keyboard press (non-blocking on Windows)
                if sys.platform == "win32":
                    try:
                        import msvcrt
                        while msvcrt.kbhit():
                            ch = msvcrt.getch()
                            if ch in (b'\r', b'\n', b' '):
                                logger.info("Terminal keypress detected.")
                                login_confirmed = True
                                break
                        if login_confirmed:
                            break
                    except Exception:
                        pass

                time.sleep(1.5)

            # Give a moment for redirects / cookies to settle
            time.sleep(2)

            try:
                cookies = driver.get_cookies() or latest_cookies
            except Exception:
                cookies = latest_cookies

            if not cookies:
                logger.error("No cookies captured. Login may have failed.")
                raise RuntimeError("No cookies captured after login.")

            # Save them encrypted
            save_cookies(cookies)

            logger.info("Captured %d cookies from myUSCIS session.", len(cookies))
            print(f"\n  [OK] Captured {len(cookies)} session cookies successfully!\n")

            return cookies

        finally:
            try:
                driver.quit()
            except Exception:
                pass


def get_valid_cookies() -> dict | None:
    """
    Get a valid cookie dict for API requests from stored cookies.
    Returns None if no saved cookies are found.
    """
    cookies = load_cookies()
    if cookies:
        logger.info("Loaded saved session cookies.")
        return cookies_to_session_dict(cookies)

    logger.warning("No saved cookies found. Please log in or paste cookies.")
    return None


def clear_cookies() -> None:
    """Delete saved cookies (forces re-login on next run)."""
    if config.COOKIES_FILE.exists():
        config.COOKIES_FILE.unlink()
        logger.info("Saved cookies deleted.")
