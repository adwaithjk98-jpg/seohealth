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
from selenium.common.exceptions import WebDriverException
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

    # Block images + fonts at the content-settings layer to trim bandwidth.
    # The DOM is unaffected — <img src="…"> tags still render in the page
    # source, so scrapers that *count* images on Google Maps work fine, we
    # just never download the JPG/PNG bytes.
    #
    # Stylesheets are NOT blocked: Google Maps' review-count sibling span
    # inside ``div.F7nice`` only paints in the DOM when CSS-driven layout
    # passes through — blocking stylesheets caused ``review_count`` to come
    # back ``None`` on every audit even though the rating extracted cleanly.
    opts.add_experimental_option(
        "prefs",
        {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.fonts": 2,
        },
    )

    chrome_binary = os.getenv("CHROME_BINARY")
    if chrome_binary:
        opts.binary_location = chrome_binary
    return opts


def _use_undetected_driver() -> bool:
    """True when we should drive Chrome through undetected-chromedriver.

    Default OFF. Google Maps strips the review-count DOM for vanilla
    Selenium AND for stock undetected-chromedriver (tested headless +
    visible). The dep is wired in here for future stealth work — bring
    a persistent profile, additional fingerprint patches, or pair with
    a residential-IP proxy — but it doesn't solve the problem on its
    own, so leaving it ON by default just trades vanilla Selenium for
    a heavier driver with no review-count win.

    Flip ``USE_UNDETECTED_CHROMEDRIVER=true`` when iterating on a real
    bypass.
    """
    return os.getenv("USE_UNDETECTED_CHROMEDRIVER", "false").lower() == "true"


def _local_chrome_major_version() -> int | None:
    """Best-effort: read the installed Chrome's major version.

    undetected-chromedriver downloads a chromedriver matched to a fixed
    Chrome version unless we hand it ``version_main``. Without this,
    ``uc.Chrome()`` raises "this version of ChromeDriver only supports
    Chrome version N" whenever the system Chrome is a release behind
    the bundled driver. Returning None lets the caller fall through to
    UC's default (and surface a clear error if it really doesn't match).
    """
    import re
    import subprocess

    candidates = [
        os.getenv("CHROME_BINARY"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium",
        "/opt/google/chrome/chrome",
    ]
    for path in candidates:
        if not path:
            continue
        try:
            out = subprocess.check_output([path, "--version"], timeout=5)
            m = re.search(r"\b(\d+)\.", out.decode("utf-8", "ignore"))
            if m:
                return int(m.group(1))
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def _build_undetected_driver() -> WebDriver:
    # Lazy import — the dependency is only loaded when the flag is on,
    # so devs running other parts of the backend don't pay for it.
    import undetected_chromedriver as uc

    uc_opts = uc.ChromeOptions()
    # Mirror the same flags as the vanilla path so the rest of the
    # scraper sees an identical Chrome environment (window size,
    # locale, bandwidth-saving content-settings, etc.).
    uc_opts.add_argument("--no-sandbox")
    uc_opts.add_argument("--disable-dev-shm-usage")
    uc_opts.add_argument("--disable-gpu")
    uc_opts.add_argument("--window-size=1366,900")
    uc_opts.add_argument("--lang=en-US,en")
    uc_opts.add_argument(f"--user-agent={DEFAULT_USER_AGENT}")
    uc_opts.add_experimental_option(
        "prefs",
        {
            "profile.managed_default_content_settings.images": 2,
            "profile.managed_default_content_settings.fonts": 2,
        },
    )
    chrome_binary = os.getenv("CHROME_BINARY")
    if chrome_binary:
        uc_opts.binary_location = chrome_binary
    return uc.Chrome(
        options=uc_opts,
        headless=True,
        use_subprocess=True,
        version_main=_local_chrome_major_version(),
    )


def _build_driver() -> WebDriver:
    if _use_undetected_driver():
        try:
            driver = _build_undetected_driver()
        except Exception as exc:
            raise DriverUnavailable(
                f"could not start undetected Chrome: {exc}"
            ) from exc
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_S)
        driver.set_script_timeout(SCRIPT_TIMEOUT_S)
        return driver

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

    # Vanilla Selenium fallback — also try the soft navigator.webdriver
    # bypass so even the fallback path has a fighting chance.
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": (
                    "Object.defineProperty(navigator, 'webdriver', "
                    "{get: () => undefined});"
                    "Object.defineProperty(navigator, 'languages', "
                    "{get: () => ['en-US', 'en']});"
                )
            },
        )
    except WebDriverException:
        pass

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
