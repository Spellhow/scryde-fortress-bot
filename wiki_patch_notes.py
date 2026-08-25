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


def fetch_wiki_patch_note(url=WIKI_URL):
    response = requests.get(
        url,
        timeout=25,
        headers={
            "User-Agent": bot.USER_AGENTS[0],
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
        },
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    next_data = soup.find("script", id="__NEXT_DATA__")
    raw = next_data.string if next_data else None
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
        "url": response.url or url,
        "text": "{}\n\n{}".format(title, plain).strip(),
        "formatted_html": "<h1>{}</h1>\n{}".format(
            html_lib.escape(title),
            content_html,
        ),
        "fingerprint": _fingerprint(title, plain),
        "updated_at": updated_at,
        "created_at": created_at,
    }


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
    except Exception as exc:
        bot.log("wiki patch notes fetch/parser failed: {}".format(exc))
        bot.send_debug(
            bot.DEBUG_CYCLE_ERROR.format(
                error="wiki patch notes: {}".format(str(exc)[:240])
            )
        )
    finally:
        bot.save_state(state)


if __name__ == "__main__":
    main()
