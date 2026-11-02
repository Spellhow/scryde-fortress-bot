#!/usr/bin/env python3

import hashlib
import html as html_lib
import json
import os
import re
import time

import requests
from bs4 import BeautifulSoup

import github_runner as bot


WIKI_URL = os.environ.get(
    "SCRYDE_WIKI_UPDATES_URL",
    "https://ru.scryde.game/wiki/articles/patch-notes/updates",
)
STATE_KEY = "forum_news"
SOURCE_MODE = "wiki_patch_notes"
WIKI_GEMINI_FALLBACK_MODEL = os.environ.get(
    "SCRYDE_WIKI_GEMINI_FALLBACK_MODEL",
    "gemini-3.1-flash-lite",
).strip()
WIKI_HTTP_RETRIES = max(1, int(os.environ.get("SCRYDE_WIKI_HTTP_RETRIES", "2")))
WIKI_BROWSER_TIMEOUT_MS = max(5000, int(os.environ.get("SCRYDE_WIKI_BROWSER_TIMEOUT_MS", "25000")))
WIKI_ERROR_NOTIFY_AFTER = max(1, int(os.environ.get("SCRYDE_WIKI_ERROR_NOTIFY_AFTER", "3")))
WIKI_ERROR_NOTIFY_COOLDOWN_SEC = max(
    600,
    int(os.environ.get("SCRYDE_WIKI_ERROR_NOTIFY_COOLDOWN_SEC", "21600")),
)
WIKI_HEALTH_KEY = "wiki_patch_notes_health"
RETRYABLE_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524}


def _visible_text(content_html):
    soup = BeautifulSoup(content_html or "", "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _fingerprint(title, plain_text):
    canonical = re.sub(r"\s+", " ", "{}\n{}".format(title or "", plain_text or "")).strip()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _article_from_next_data(raw, final_url):
    if not raw:
        raise ValueError("wiki __NEXT_DATA__ missing")

    data = json.loads(raw)
    try:
        article = data["props"]["pageProps"]["preloadedArticle"]
    except (KeyError, TypeError) as exc:
        raise ValueError("wiki preloadedArticle missing") from exc

    if not isinstance(article, dict):
        raise ValueError("wiki preloadedArticle is not an object")

    title = str(article.get("title") or "").strip()
    content_html = str(article.get("content") or "").strip()
    if not title or not content_html:
        raise ValueError("wiki article title/content missing")

    plain = _visible_text(content_html)
    updated_at = int(article.get("updated_at") or 0)
    created_at = int(article.get("created_at") or 0)
    article_id = int(article.get("id") or 0)
    version_id = updated_at or created_at or int(time.time())

    return {
        "id": version_id,
        "article_id": article_id,
        "title": title,
        "url": final_url or WIKI_URL,
        "text": "{}\n\n{}".format(title, plain).strip(),
        "formatted_html": "<h1>{}</h1>\n{}".format(
            html_lib.escape(title),
            content_html,
        ),
        "fingerprint": _fingerprint(title, plain),
        "updated_at": updated_at,
        "created_at": created_at,
    }


def _parse_wiki_patch_note(page_html, final_url):
    soup = BeautifulSoup(page_html or "", "html.parser")
    next_data = soup.find("script", id="__NEXT_DATA__")
    raw = next_data.string if next_data else None
    return _article_from_next_data(raw, final_url)


def _looks_like_variti_challenge(page_html):
    text = (page_html or "").lower()
    return (
        "<title>..</title>" in text
        and "javascript disabled" in text
        and "__next_data__" not in text
    )


def _request_wiki_page(url):
    last_error = None
    for attempt in range(1, WIKI_HTTP_RETRIES + 1):
        try:
            response = requests.get(
                url,
                timeout=(10, 25),
                headers={
                    "User-Agent": bot.USER_AGENTS[0],
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
                    "Cache-Control": "no-cache",
                },
            )
            if response.status_code in RETRYABLE_HTTP_CODES:
                last_error = requests.HTTPError(
                    "{} Server Error for url: {}".format(response.status_code, response.url or url)
                )
                bot.log(
                    "wiki HTTP attempt {}/{} got {}; retrying/falling back".format(
                        attempt,
                        WIKI_HTTP_RETRIES,
                        response.status_code,
                    )
                )
                if attempt < WIKI_HTTP_RETRIES:
                    time.sleep(min(2 ** (attempt - 1), 3))
                    continue
                return None, response.url or url, last_error

            response.raise_for_status()
            return response.text, response.url or url, None
        except requests.RequestException as exc:
            last_error = exc
            bot.log(
                "wiki HTTP attempt {}/{} failed: {}".format(
                    attempt,
                    WIKI_HTTP_RETRIES,
                    str(exc)[:180],
                )
            )
            if attempt < WIKI_HTTP_RETRIES:
                time.sleep(min(2 ** (attempt - 1), 3))

    return None, url, last_error


def _extract_browser_article(page, final_url):
    last_error = None
    for attempt in range(1, 5):
        try:
            raw = page.locator("script#__NEXT_DATA__").text_content(timeout=4000)
            article = _article_from_next_data(raw, final_url)
            if attempt > 1:
                bot.log(
                    "wiki Chromium NEXT_DATA recovered on extraction attempt {}".format(attempt)
                )
            return article
        except (json.JSONDecodeError, ValueError, bot.PlaywrightError) as exc:
            last_error = exc
            if attempt >= 4:
                break
            bot.log(
                "wiki Chromium NEXT_DATA not ready on extraction attempt {}: {}".format(
                    attempt,
                    str(exc)[:180],
                )
            )
            page.wait_for_timeout(500 * attempt)

    raise ValueError(
        "wiki Chromium NEXT_DATA remained invalid after retries: {}".format(
            str(last_error)[:220]
        )
    )


def _fetch_wiki_article_browser(url):
    with bot.sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            chrome_version = str(browser.version or "122.0.0.0")
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/{} Safari/537.36".format(chrome_version)
            )
            context = browser.new_context(
                user_agent=user_agent,
                locale="ru-RU",
                timezone_id="Europe/Vilnius",
                viewport={"width": 1366, "height": 768},
                extra_http_headers={"Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7"},
            )
            page = context.new_page()
            page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in {"image", "font", "media"}
                else route.continue_(),
            )

            last_error = None
            for navigation_attempt in range(1, 3):
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=WIKI_BROWSER_TIMEOUT_MS,
                )
                try:
                    page.wait_for_selector(
                        "script#__NEXT_DATA__",
                        state="attached",
                        timeout=WIKI_BROWSER_TIMEOUT_MS,
                    )
                    final_url = page.url or url
                    return _extract_browser_article(page, final_url)
                except (bot.PlaywrightTimeoutError, ValueError) as exc:
                    last_error = exc
                    if navigation_attempt >= 2:
                        status = response.status if response is not None else "unknown"
                        title = ""
                        try:
                            title = page.title()
                        except Exception:
                            pass
                        raise ValueError(
                            "wiki browser fallback failed after navigation retries "
                            "(status={}, title={!r}): {}".format(
                                status,
                                title,
                                str(exc)[:220],
                            )
                        ) from exc
                    bot.log(
                        "wiki Chromium navigation/extraction attempt {} failed: {}; reloading".format(
                            navigation_attempt,
                            str(exc)[:180],
                        )
                    )
                    page.wait_for_timeout(800)

            raise ValueError("wiki browser fallback failed: {}".format(last_error))
        finally:
            browser.close()


def fetch_wiki_patch_note(url=WIKI_URL):
    request_html, request_url, request_error = _request_wiki_page(url)
    if request_html:
        try:
            article = _parse_wiki_patch_note(request_html, request_url)
            bot.log("wiki patch notes fetched via HTTP")
            return article
        except ValueError as exc:
            if _looks_like_variti_challenge(request_html):
                bot.log("wiki HTTP received Variti JS challenge; switching to Chromium")
            else:
                bot.log(
                    "wiki HTTP page was not parseable ({}); switching to Chromium".format(
                        str(exc)[:180]
                    )
                )
            request_error = exc
    elif request_error:
        bot.log("wiki HTTP unavailable; switching to Chromium")

    try:
        article = _fetch_wiki_article_browser(url)
        bot.log("wiki patch notes fetched via Chromium fallback")
        return article
    except Exception as browser_exc:
        if request_error:
            raise RuntimeError(
                "HTTP failed ({0}); Chromium fallback failed ({1})".format(
                    str(request_error)[:180],
                    str(browser_exc)[:220],
                )
            ) from browser_exc
        raise


def _record_wiki_failure(state, exc):
    now = int(time.time())
    health = state.setdefault(WIKI_HEALTH_KEY, {})
    count = int(health.get("consecutive_failures", 0) or 0) + 1
    last_notified_at = int(health.get("last_notified_at", 0) or 0)
    message = str(exc)[:500]

    health["consecutive_failures"] = count
    health["last_failure_at"] = now
    health["last_error"] = message

    should_notify = count >= WIKI_ERROR_NOTIFY_AFTER and (
        not last_notified_at
        or now - last_notified_at >= WIKI_ERROR_NOTIFY_COOLDOWN_SEC
    )
    if should_notify:
        health["last_notified_at"] = now
        bot.send_debug(
            bot.DEBUG_CYCLE_ERROR.format(
                error="wiki patch notes: {} consecutive failures; {}".format(
                    count,
                    message[:220],
                )
            )
        )
    else:
        bot.log(
            "wiki failure notification suppressed (consecutive_failures={})".format(count)
        )


def _clear_wiki_failure(state):
    if WIKI_HEALTH_KEY in state:
        state.pop(WIKI_HEALTH_KEY, None)
        bot.log("wiki patch notes fetch health recovered")


def _news_state(state):
    return state.setdefault(
        STATE_KEY,
        {"last_seen_id": 0, "sent_ids": [], "pending": []},
    )


def _remember_source(news_state, article, add_sent_id=False):
    news_state["source_mode"] = SOURCE_MODE
    news_state["wiki_article_id"] = article["article_id"]
    news_state["wiki_title"] = article["title"]
    news_state["wiki_fingerprint"] = article["fingerprint"]
    news_state["wiki_updated_at"] = article["updated_at"]

    current_last_seen = int(news_state.get("last_seen_id", 0) or 0)
    news_state["last_seen_id"] = max(current_last_seen, int(article["id"]))

    if add_sent_id:
        sent_ids = set(news_state.get("sent_ids", []))
        sent_ids.add(int(article["id"]))
        news_state["sent_ids"] = sorted(sent_ids)[-50:]


def _same_title_pending(news_state, source_title):
    for item in reversed(news_state.get("pending", [])):
        if item.get("status") not in {"pending", "approved"}:
            continue
        if item.get("source") != "wiki":
            continue
        if item.get("source_title") == source_title:
            return item
    return None


def _replacement_target(state, rewritten):
    state_key = rewritten.get("target_state_key")
    post_id = int(rewritten.get("target_post_id", 0) or 0)
    if state_key not in {"news", "forum_news"} or not post_id:
        return None

    target_state = state.setdefault(
        state_key,
        {"last_seen_id": 0, "sent_ids": [], "pending": []},
    )
    for item in target_state.get("pending", []):
        if int(item.get("post_id", 0) or 0) != post_id:
            continue
        if item.get("status") in {"pending", "approved"}:
            return item
    return None


def _rewrite(article, state):
    kwargs = {
        "source_label": "wiki",
        "pending_context": bot.build_pending_context(state),
        "source_html": article["formatted_html"],
    }
    rewritten = bot.gemini_rewrite_x1000_news(
        article["text"],
        retries_override=2,
        **kwargs,
    )
    if rewritten or not WIKI_GEMINI_FALLBACK_MODEL or WIKI_GEMINI_FALLBACK_MODEL == bot.GEMINI_MODEL:
        return rewritten

    bot.log(
        "wiki primary Gemini unavailable; retrying with fallback model {}".format(
            WIKI_GEMINI_FALLBACK_MODEL
        )
    )
    return bot.gemini_rewrite_x1000_news(
        article["text"],
        model_override=WIKI_GEMINI_FALLBACK_MODEL,
        retries_override=2,
        **kwargs,
    )


def _apply_pending_content(item, article, rewritten, reset_delay=True):
    body = str(rewritten.get("text") or "").strip()
    title = str(rewritten.get("title") or "Оновлення Scryde x1000").strip()
    if not body:
        return False

    now = int(time.time())
    item["title"] = "⚙️ {}".format(title)
    item["text"] = body
    item["url"] = article["url"]
    item["source"] = "wiki"
    item["source_title"] = article["title"]
    item["source_fingerprint"] = article["fingerprint"]
    item["wiki_article_id"] = article["article_id"]
    item["wiki_updated_at"] = article["updated_at"]

    if reset_delay:
        item["status"] = "pending"
        item["created_at"] = now
        item["publish_after"] = now + bot.NEWS_APPROVE_DELAY_MIN * 60

    if item.get("debug_message_id"):
        item["debug_preview_version"] = 0
    elif bot.TG_CHAT_DEBUG:
        preview = bot.build_pending_preview(
            "wiki",
            item["title"],
            item["text"],
            item["url"],
            updated=True,
        )
        item["debug_message_id"] = bot.send_telegram_with_markup(
            preview,
            None,
            chat_id=bot.TG_CHAT_DEBUG,
        )
        item["debug_preview_version"] = bot.NEWS_DEBUG_PREVIEW_VERSION
    return True


def _queue_new_item(state, news_state, article, rewritten):
    if rewritten.get("action") == "ignore":
        bot.log("wiki update ignored by Gemini: {}".format(article["title"]))
        return True

    body = str(rewritten.get("text") or "").strip()
    title = str(rewritten.get("title") or "Оновлення Scryde x1000").strip()
    if not body:
        return False

    target = None
    if rewritten.get("action") == "replace":
        target = _replacement_target(state, rewritten)

    if target is not None:
        if not _apply_pending_content(target, article, rewritten, reset_delay=True):
            return False
        bot.log(
            "wiki update replaced pending {} {}".format(
                rewritten.get("target_state_key"),
                rewritten.get("target_post_id"),
            )
        )
        return True

    if rewritten.get("action") == "ignore":
        bot.log("wiki update ignored by Gemini: {}".format(article["title"]))
        return True

    now = int(time.time())
    pending_item = {
        "post_id": int(article["id"]),
        "title": "⚙️ {}".format(title),
        "text": body,
        "url": article["url"],
        "created_at": now,
        "publish_after": now + bot.NEWS_APPROVE_DELAY_MIN * 60,
        "status": "pending",
        "debug_message_id": None,
        "debug_preview_version": bot.NEWS_DEBUG_PREVIEW_VERSION,
        "source": "wiki",
        "source_title": article["title"],
        "source_fingerprint": article["fingerprint"],
        "wiki_article_id": article["article_id"],
        "wiki_updated_at": article["updated_at"],
    }

    if bot.TG_CHAT_DEBUG:
        preview = bot.build_pending_preview(
            "wiki",
            pending_item["title"],
            pending_item["text"],
            pending_item["url"],
        )
        pending_item["debug_message_id"] = bot.send_telegram_with_markup(
            preview,
            None,
            chat_id=bot.TG_CHAT_DEBUG,
        )

    news_state.setdefault("pending", []).append(pending_item)
    news_state["pending"] = news_state["pending"][-50:]
    bot.log(
        "wiki queued new patch note {} as post_id={}".format(
            article["title"],
            article["id"],
        )
    )
    return True


def process_wiki_patch_notes(state):
    article = fetch_wiki_patch_note()
    news_state = _news_state(state)
    previous_title = str(news_state.get("wiki_title") or "")
    previous_fingerprint = str(news_state.get("wiki_fingerprint") or "")

    if previous_fingerprint == article["fingerprint"]:
        _remember_source(news_state, article)
        bot.log("wiki patch notes unchanged: {}".format(article["title"]))
        return True

    if previous_title and previous_title == article["title"]:
        pending = _same_title_pending(news_state, article["title"])
        if pending is None:
            _remember_source(news_state, article)
            bot.log(
                "wiki same-title revision detected after final handling; "
                "updated fingerprint without duplicate post: {}".format(article["title"])
            )
            return True

        rewritten = _rewrite(article, state)
        if not rewritten:
            bot.log("wiki same-title revision rewrite failed; will retry")
            return False

        if not rewritten.get("relevant") or rewritten.get("action") == "ignore":
            pending["status"] = "cancelled"
            _remember_source(news_state, article, add_sent_id=True)
            bot.log(
                "wiki same-title revision became irrelevant/ignored; "
                "cancelled stale pending item"
            )
            return True

        if not _apply_pending_content(pending, article, rewritten, reset_delay=True):
            bot.log("wiki same-title revision produced empty body; will retry")
            return False

        _remember_source(news_state, article, add_sent_id=True)
        bot.log("wiki pending patch note refreshed from same-title revision")
        return True

    rewritten = _rewrite(article, state)
    if not rewritten:
        bot.log("wiki patch note rewrite failed; will retry without advancing state")
        return False

    if not rewritten.get("relevant"):
        _remember_source(news_state, article, add_sent_id=True)
        bot.log("wiki patch note is not relevant to x1000: {}".format(article["title"]))
        return True

    if not _queue_new_item(state, news_state, article, rewritten):
        bot.log("wiki patch note produced empty body; will retry")
        return False

    _remember_source(news_state, article, add_sent_id=True)
    return True


def main():
    state = bot.load_state()
    try:
        process_wiki_patch_notes(state)
        _clear_wiki_failure(state)
    except Exception as exc:
        bot.log("wiki patch notes fetch/parser failed: {}".format(exc))
        _record_wiki_failure(state, exc)
    finally:
        bot.save_state(state)


if __name__ == "__main__":
    main()
