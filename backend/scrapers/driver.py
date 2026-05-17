"""Headless Chrome driver management for the audit scrapers.

Provides:
- ``chrome_driver()`` — context manager that yields a configured headless
  Chrome WebDriver and guarantees ``driver.quit()`` on exit (even on errors).
- ``CaptchaDetected`` — exception raised when a scraper hits Google's
  ``/sorry/`` CAPTCHA wall or a similar consent challenge.
- ``detect_captcha()`` — quick page sniff used by Maps before extraction.

A semaphore caps concurrent driver creation. Chrome is RAM-heavy
(~600–900 MB per instance per AuditAppPlan §4) and unbounded parallel audits
will OOM a small VPS.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Iterator

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.remote.webdriver import WebDriver

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Cap concurrent Chrome instances. Override with AUDIT_MAX_CONCURRENT_DRIVERS.
# This is a process-local threading.Semaphore — it caps drivers within
# *this* worker process only. The deployment model is one RQ worker
# process running one job at a time, so the default cap of 1 matches the
# actual concurrency. Bumping this without also moving to a Redis-backed
# semaphore (and rethinking horizontal worker scaling) will not give you
# more parallelism — it will just under-cap a single process. See
# project_notes.md "Concurrency cap" for the full rationale.
_MAX_CONCURRENT = int(os.getenv("AUDIT_MAX_CONCURRENT_DRIVERS", "1"))
_DRIVER_SEMAPHORE = threading.Semaphore(_MAX_CONCURRENT)

PAGE_LOAD_TIMEOUT_S = int(os.getenv("AUDIT_PAGE_TIMEOUT", "30"))
SCRIPT_TIMEOUT_S = int(os.getenv("AUDIT_SCRIPT_TIMEOUT", "20"))


class CaptchaDetected(RuntimeError):
    """Google (or another source) is asking us to solve a CAPTCHA."""


class DriverUnavailable(RuntimeError):
    """We could not start a Chrome driver (binary missing, etc.)."""


def _build_options() -> Options:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1366,900")
    opts.add_argument("--lang=en-US,en")
    opts.add_argument(f"--user-agent={DEFAULT_USER_AGENT}")
    # Soft anti-detection — does not defeat real bot defenses, but trims the
    # most obvious automation tells so we don't get flagged on the first hit.
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # Block heavy media (images, stylesheets, fonts) at the content-settings
    # layer. The DOM is unaffected — <img src="…"> tags still render in the
    # page source, so scrapers that *count* images on Google Maps work fine,
    # we just never download the JPG/PNG bytes. Saves substantial proxy
    # bandwidth on every audit run.
    opts.add_experimental_option(
        "prefs",
        {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.stylesheets": 2,
            "profile.managed_default_content_settings.fonts": 2,
        },
    )

    chrome_binary = os.getenv("CHROME_BINARY")
    if chrome_binary:
        opts.binary_location = chrome_binary
    return opts


def _build_driver() -> WebDriver:
    options = _build_options()
    chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
    try:
        if chromedriver_path:
            driver = webdriver.Chrome(service=Service(executable_path=chromedriver_path), options=options)
        else:
            driver = webdriver.Chrome(options=options)
    except Exception as exc:
        raise DriverUnavailable(f"could not start Chrome: {exc}") from exc

    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_S)
    driver.set_script_timeout(SCRIPT_TIMEOUT_S)
    return driver


@contextmanager
def chrome_driver() -> Iterator[WebDriver]:
    """Yield a headless Chrome driver, guaranteeing cleanup on exit."""
    _DRIVER_SEMAPHORE.acquire()
    driver: WebDriver | None = None
    try:
        driver = _build_driver()
        yield driver
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                logger.exception("driver.quit() failed")
        _DRIVER_SEMAPHORE.release()


_CAPTCHA_URL_MARKERS = ("/sorry/", "captcha", "consent.google")
_CAPTCHA_BODY_MARKERS = (
    "our systems have detected unusual traffic",
    "unusual traffic from your computer",
    "to continue, please type the characters",
    "recaptcha",
)


def detect_captcha(driver: WebDriver) -> None:
    """Raise CaptchaDetected if the current page looks like a CAPTCHA wall."""
    try:
        url = (driver.current_url or "").lower()
    except Exception:
        url = ""
    for marker in _CAPTCHA_URL_MARKERS:
        if marker in url:
            raise CaptchaDetected(f"captcha url: {url}")

    try:
        title = (driver.title or "").lower()
    except Exception:
        title = ""
    if "captcha" in title or "unusual traffic" in title:
        raise CaptchaDetected(f"captcha title: {title}")

    try:
        sample = driver.page_source[:4000].lower()
    except Exception:
        return
    for marker in _CAPTCHA_BODY_MARKERS:
        if marker in sample:
            raise CaptchaDetected(f"captcha marker: {marker}")
