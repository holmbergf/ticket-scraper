from __future__ import annotations

import logging
import os
import random
import signal
import shutil
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable

import urllib3

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
)

_chrome_path_cache: str | None = None
_chrome_path_resolved: bool = False

RETRYABLE_TOKENS = ("timeout", "network error", "503", "502", "429")

_pool = urllib3.PoolManager(
    num_pools=10,
    maxsize=12,
    retries=False,
    timeout=urllib3.Timeout(connect=10, read=30),
)


@dataclass(slots=True)
class FetchResponse:
    url: str
    status_code: int
    text: str


class FetchError(RuntimeError):
    pass


@dataclass(slots=True)
class BrowserFetchConfig:
    chrome_path: str | None = None
    browser_timeout_s: float = 20.0
    user_agent: str = DEFAULT_USER_AGENT
    max_retries: int = 2
    base_delay_s: float = 1.5


def _is_retryable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(tok in msg for tok in RETRYABLE_TOKENS)


def _retry_delay(attempt: int, base: float) -> float:
    delay = base * (2 ** attempt)
    jitter = random.uniform(0, delay * 0.3)
    return delay + jitter


def fetch_text(url: str, timeout: float = 30.0, user_agent: str = DEFAULT_USER_AGENT) -> FetchResponse:
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Cache-Control": "no-cache",
    }
    try:
        resp = _pool.request(
            "GET",
            url,
            headers=headers,
            timeout=urllib3.Timeout(connect=10, read=timeout),
            redirect=True,
            preload_content=True,
            decode_content=True,
        )
        if resp.status >= 400:
            raise FetchError(f"HTTP error fetching {url}: {resp.status}")
        charset = resp.headers.get("Content-Type", "")
        enc = "utf-8"
        if "charset=" in charset:
            enc = charset.split("charset=")[-1].split(";")[0].strip()
        text = resp.data.decode(enc, errors="replace")
        if _looks_like_challenge_page(text):
            raise FetchError(f"Challenge page returned for {url}")
        final_url = resp.geturl() or url
        log.debug("HTTP OK %s (%d bytes)", url, len(text))
        return FetchResponse(url=final_url, status_code=resp.status, text=text)
    except FetchError:
        raise
    except urllib3.exceptions.TimeoutError as exc:
        raise FetchError(f"Timeout fetching {url}") from exc
    except urllib3.exceptions.HTTPError as exc:
        raise FetchError(f"Network error fetching {url}: {exc}") from exc


def fetch_text_browser(url: str, timeout: float = 30.0, config: BrowserFetchConfig | None = None) -> FetchResponse:
    config = config or BrowserFetchConfig()
    chrome_path = _get_chrome_path(config.chrome_path)
    if chrome_path is None:
        raise FetchError("Browser fallback requested but no Chrome executable was found")

    effective_timeout = config.browser_timeout_s

    profile_dir = tempfile.mkdtemp(prefix="fifa_browser_")
    try:
        cmd = [
            chrome_path,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-default-apps",
            "--disable-extensions",
            "--disable-sync",
            "--mute-audio",
            "--no-first-run",
            "--window-size=1440,900",
            "--lang=en-US",
            f"--user-agent={config.user_agent}",
            f"--user-data-dir={profile_dir}",
            "--dump-dom",
            url,
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            env={**os.environ, "HOME": os.environ.get("HOME", profile_dir)},
        )
        try:
            stdout, stderr = proc.communicate(timeout=effective_timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            stdout, stderr = proc.communicate(timeout=5)
            html = _coerce_output_text(stdout).strip()
            if html and not _looks_like_challenge_page(html):
                log.debug("Browser timeout-partial OK %s (%d bytes)", url, len(html))
                return FetchResponse(url=url, status_code=200, text=html)
            raise FetchError(f"Browser timeout fetching {url}")

        html = _coerce_output_text(stdout).strip()
        if not html:
            err_text = _coerce_output_text(stderr).strip()
            raise FetchError(f"Browser fetch produced no DOM for {url}: {err_text or f'exit {proc.returncode}'}")
        if _looks_like_challenge_page(html):
            raise FetchError(f"Challenge page returned for {url}")
        log.debug("Browser OK %s (%d bytes)", url, len(html))
        return FetchResponse(url=url, status_code=200, text=html)
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Playwright-based fetch (handles JS challenges, lazy-loading, cookie reuse)
# ---------------------------------------------------------------------------

_pw_local = threading.local()
_pw_domain_locks: dict[str, threading.Lock] = {}
_pw_domain_last: dict[str, float] = {}
_pw_meta_lock = threading.Lock()
_PW_MIN_INTERVAL = 3.0


def _get_playwright_browser():
    browser = getattr(_pw_local, "browser", None)
    if browser is not None and browser.is_connected():
        return browser

    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    # DataDome scores Playwright's bundled Chromium materially worse than
    # an installed Google Chrome build (verified on StubHub/Viagogo: the
    # same session gets a CAPTCHA wall in bundled Chromium and a 200 in
    # Chrome). Prefer Chrome when present; fall back for minimal images.
    browser = None
    channel = os.getenv("PLAYWRIGHT_CHANNEL", "chrome")
    attempts = ([{"channel": channel}] if channel else []) + [{}]
    last_exc: Exception | None = None
    for kwargs in attempts:
        try:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
                **kwargs,
            )
            log.debug("Playwright browser launched (channel=%s)", kwargs.get("channel", "bundled"))
            break
        except Exception as exc:  # Chrome not installed in this image
            last_exc = exc
    if browser is None:
        pw.stop()
        raise FetchError(f"Could not launch Playwright browser: {last_exc}")
    _pw_local.pw = pw
    _pw_local.browser = browser
    _pw_local.contexts = {}
    return browser


def _get_playwright_context(url: str):
    from urllib.parse import urlparse
    domain = urlparse(url).netloc
    contexts = getattr(_pw_local, "contexts", {})

    ctx = contexts.get(domain)
    if ctx is not None:
        try:
            ctx.pages
            return ctx
        except Exception:
            contexts.pop(domain, None)

    browser = _get_playwright_browser()
    # Do not force Sec-Fetch-* headers: Chrome sets them per navigation,
    # and pinning cross-site values onto same-site warmup navigations is
    # itself a DataDome signal (verified: StubHub event pages 403 with
    # the pinned headers and 200 without, in the same warmed session).
    ctx = browser.new_context(
        user_agent=DEFAULT_USER_AGENT,
        viewport={"width": 1440, "height": 900},
        locale="en-US",
    )
    ctx.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    contexts[domain] = ctx
    _pw_local.contexts = contexts
    return ctx


def close_playwright() -> None:
    for ctx in getattr(_pw_local, "contexts", {}).values():
        try:
            ctx.close()
        except Exception:
            pass
    _pw_local.contexts = {}
    for attr in ("browser", "pw"):
        obj = getattr(_pw_local, attr, None)
        if obj is None:
            continue
        try:
            if attr == "pw":
                obj.stop()
            else:
                obj.close()
        except Exception:
            pass
        setattr(_pw_local, attr, None)


def fetch_text_playwright(
    url: str,
    timeout: float = 30.0,
    wait_until: str = "domcontentloaded",
    scroll: bool = False,
    min_interval: float | None = None,
    wait_selector: str | None = None,
    warmup_urls: tuple[str, ...] = (),
) -> FetchResponse:
    from urllib.parse import urlparse
    domain = urlparse(url).netloc
    effective_interval = min_interval if min_interval is not None else _PW_MIN_INTERVAL
    with _pw_meta_lock:
        if domain not in _pw_domain_locks:
            _pw_domain_locks[domain] = threading.Lock()
            _pw_domain_last[domain] = 0.0
    lock = _pw_domain_locks[domain]
    with lock:
        elapsed = time.monotonic() - _pw_domain_last[domain]
        if elapsed < effective_interval:
            time.sleep(effective_interval - elapsed)
        _pw_domain_last[domain] = time.monotonic()

    ctx = _get_playwright_context(url)
    page = ctx.new_page()
    try:
        timeout_ms = int(timeout * 1000)
        # Some WAFs (DataDome on StubHub) serve a CAPTCHA wall to a cold
        # deep link but allow the same session after ordinary entry-point
        # pages set first-party cookies. Warm this context once, in order.
        warmed = getattr(_pw_local, "warmed", set())
        for warm_url in warmup_urls:
            marker = (id(ctx), warm_url)
            if marker in warmed or warm_url == url:
                continue
            warmed.add(marker)
            try:
                log.debug("Warming Playwright session via %s", warm_url)
                page.goto(warm_url, wait_until=wait_until, timeout=timeout_ms)
                page.wait_for_timeout(2500)
            except Exception as exc:
                log.warning("Warmup fetch failed for %s: %s", warm_url, exc)
        _pw_local.warmed = warmed

        response = page.goto(url, wait_until=wait_until, timeout=timeout_ms)

        # Wait for AWS WAF / DataDome challenges to resolve.
        # Discovery/grouping pages may need longer; event pages have
        # cookies already set so 2 polls usually suffice.
        is_grouping = "/grouping/" in url
        max_polls = 8 if (scroll or is_grouping) else 2
        for i in range(max_polls):
            html_check = page.content()
            if not _looks_like_challenge_page(html_check):
                break
            log.debug("Challenge detected on %s (poll %d/%d), waiting…", url, i + 1, max_polls)
            page.wait_for_timeout(3000 + i * 1000)
        else:
            page.wait_for_timeout(1000)

        if wait_selector:
            try:
                page.wait_for_selector(wait_selector, timeout=min(timeout_ms, 20_000))
            except Exception:
                log.warning("Timed out waiting for selector %s on %s", wait_selector, url)

        if scroll:
            prev_height = 0
            for _ in range(15):
                page.evaluate("window.scrollBy(0, window.innerHeight)")
                page.wait_for_timeout(600)
                cur_height = page.evaluate("document.body.scrollHeight")
                if cur_height == prev_height:
                    break
                prev_height = cur_height
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(500)

        html = page.content()
        status = response.status if response else 200

        if _looks_like_challenge_page(html):
            raise FetchError(f"Challenge page returned for {url}")
        if status >= 400:
            # A bot-wall device check can answer 401/403/429 first and then
            # reload into the real page. The initial status alone should
            # not discard content that has since rendered successfully.
            if status in (401, 403, 429) and len(html) > _CHALLENGE_PAGE_MAX_BYTES:
                log.warning("Initial HTTP %s for %s recovered into rendered content", status, url)
                status = 200
            else:
                raise FetchError(f"HTTP error fetching {url}: {status}")

        final_url = page.url
        log.debug("Playwright OK %s (%d bytes)", url, len(html))
        return FetchResponse(url=final_url, status_code=status, text=html)
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"Playwright error fetching {url}: {exc}") from exc
    finally:
        page.close()


def fetch_auto(url: str, timeout: float = 30.0, config: BrowserFetchConfig | None = None) -> FetchResponse:
    try:
        return fetch_text(url, timeout=timeout)
    except FetchError as exc:
        message = str(exc).lower()
        if any(token in message for token in ("403", "429", "challenge")):
            log.info("Plain HTTP failed for %s, falling back to headless Chrome", url)
            return fetch_text_browser(url, timeout=timeout, config=config)
        raise


def fetch_with_retry(
    url: str,
    *,
    fetch_fn: Callable[[str], FetchResponse],
    max_retries: int = 2,
    base_delay_s: float = 1.5,
) -> FetchResponse:
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return fetch_fn(url)
        except FetchError as exc:
            last_exc = exc
            if attempt < max_retries and _is_retryable(exc):
                delay = _retry_delay(attempt, base_delay_s)
                log.warning("Retry %d/%d for %s after %.1fs: %s", attempt + 1, max_retries, url, delay, exc)
                time.sleep(delay)
            else:
                raise
    raise last_exc  # type: ignore[misc]


def fetch_many(
    urls: list[str],
    *,
    fetch_fn: Callable[[str], FetchResponse],
    max_workers: int = 8,
    on_result: Callable[[str, FetchResponse], None] | None = None,
    on_error: Callable[[str, Exception], None] | None = None,
) -> dict[str, FetchResponse]:
    results: dict[str, FetchResponse] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_url = {pool.submit(fetch_fn, url): url for url in urls}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                response = future.result()
                results[url] = response
                if on_result:
                    on_result(url, response)
            except Exception as exc:
                if on_error:
                    on_error(url, exc)
    return results


# Interstitial / bot-check HTML is usually a small shell; real listing pages are much larger.
_CHALLENGE_PAGE_MAX_BYTES = 10 * 1024


def _looks_like_challenge_page(text: str) -> bool:
    if len(text) > _CHALLENGE_PAGE_MAX_BYTES:
        return False
    lowered = text.lower()
    # Prefer vendor- and title-specific strings; avoid bare "captcha"/"challenge" (noisy on real pages).
    markers = (
        "<title>challenge validation</title>",
        "<title>vercel security checkpoint</title>",
        'provider="crypto"',
        "cf-challenge-platform",
        "cf-chl-bypass",
        "__cf_chl_",
        "captcha-delivery.com",
        "geo.captcha-delivery.com",
        "datadome.co",
        "dd_cookie_test",
        "we're verifying your browser",
        "checking your browser before accessing",
        "enable javascript to continue",
        "vercel security checkpoint",
        "awswafcookiedomainlist",
        "token.awswaf.com",
    )
    return any(marker in lowered for marker in markers)


def _kill_process_tree(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def _get_chrome_path(explicit_path: str | None = None) -> str | None:
    global _chrome_path_cache, _chrome_path_resolved
    if explicit_path:
        return explicit_path if os.path.exists(explicit_path) else None
    if _chrome_path_resolved:
        return _chrome_path_cache
    _chrome_path_cache = _resolve_chrome_path(None)
    _chrome_path_resolved = True
    return _chrome_path_cache


def _resolve_chrome_path(explicit_path: str | None) -> str | None:
    candidates = [
        explicit_path,
        os.environ.get("CHROME_PATH"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        shutil.which("google-chrome"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _coerce_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
