#!/usr/bin/env python3

import json
import os
import random
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

from messages import (
    OBJ,
    SIEGE_ATTACK,
    SIEGE_REMINDER,
    SIEGE_CANCELLED,
    OBJECT_LOST,
    WE_ATTACK,
    WE_CANCELLED,
    DEBUG_CYCLE_ERROR,
    DEBUG_SITE_DOWN,
    DEBUG_SITE_UP,
)

try:
    from card_builder import build_card, C_GOLD, C_RED
    CARDS_ENABLED = True
except Exception:
    CARDS_ENABLED = False
    build_card = None
    C_GOLD = None
    C_RED = None

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception as exc:
    raise SystemExit("Playwright is required in GitHub Actions runner: {}".format(exc))


TG_TOKEN = os.environ["TG_TOKEN"]
TG_CHAT = os.environ["TG_CHAT"]
TG_CHAT_DEBUG = os.environ.get("TG_CHAT_DEBUG", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
GEMINI_THINKING_LEVEL = "HIGH"
NEWS_TARGET_CHAT = os.environ.get("NEWS_TARGET_CHAT", "debug")
NEWS_TEST_POST_IDS = [int(x) for x in os.environ.get("NEWS_TEST_POST_IDS", "").split(",") if x.strip().isdigit()]
NEWS_APPROVE_DELAY_MIN = int(os.environ.get("NEWS_APPROVE_DELAY_MIN", "25"))
OUR_CLAN = os.environ.get("OUR_CLAN", "BSOE")
FORTRESS_URL = os.environ.get("FORTRESS_URL", "https://ua.scryde.game/rankings/1000/fortresses")
CASTLE_URL = os.environ.get("CASTLE_URL", "https://ua.scryde.game/rankings/1000/castles")
SCRYDE_CHANNEL_URL = os.environ.get("SCRYDE_CHANNEL_URL", "https://t.me/s/scryde")
SCRYDE_FORUM_UPDATES_URL = os.environ.get("SCRYDE_FORUM_UPDATES_URL", "https://board.scryde.net/threads/obnovlenija.30694/page-19")
STATE_FILE = os.environ.get("STATE_FILE", "site_state.json")

BETWEEN_REQUESTS_DELAY = (4, 9)
PRE_FETCH_DELAY = (8, 20)
BACKOFF_MINUTES_ON_CHALLENGE = int(os.environ.get("BACKOFF_MINUTES_ON_CHALLENGE", "60"))
SITE_ERROR_NOTIFY_AFTER = 2
GAME_TZ = ZoneInfo("Europe/Kyiv")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

_error_counts = {"fortresses": 0, "castles": 0}
_challenge_counts = {"fortresses": 0, "castles": 0}


def log(msg):
    print("{} {}".format(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def send_telegram(text, retries=3, chat_id=None):
    url = "https://api.telegram.org/bot{}/sendMessage".format(TG_TOKEN)
    payload = {
        "chat_id": chat_id or TG_CHAT,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=20)
            r.raise_for_status()
            return True
        except Exception as exc:
            log("TG send failed {}/{}: {}".format(attempt, retries, exc))
            if attempt < retries:
                time.sleep(2 * attempt)
    return False


def send_telegram_with_markup(text, reply_markup, retries=3, chat_id=None):
    url = "https://api.telegram.org/bot{}/sendMessage".format(TG_TOKEN)
    payload = {
        "chat_id": chat_id or TG_CHAT,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "reply_markup": reply_markup,
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=20)
            r.raise_for_status()
            result = r.json().get("result", {})
            return result.get("message_id")
        except Exception as exc:
            log("TG send with markup failed {}/{}: {}".format(attempt, retries, exc))
            if attempt < retries:
                time.sleep(2 * attempt)
    return None


def edit_telegram_reply_markup(chat_id, message_id, reply_markup=None):
    url = "https://api.telegram.org/bot{}/editMessageReplyMarkup".format(TG_TOKEN)
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "reply_markup": reply_markup or {"inline_keyboard": []},
    }
    try:
        r = requests.post(url, json=payload, timeout=20)
        r.raise_for_status()
        return True
    except Exception as exc:
        log("edit reply markup failed: {}".format(exc))
        return False


def answer_callback_query(callback_query_id, text):
    url = "https://api.telegram.org/bot{}/answerCallbackQuery".format(TG_TOKEN)
    try:
        r = requests.post(url, json={"callback_query_id": callback_query_id, "text": text}, timeout=20)
        r.raise_for_status()
        return True
    except Exception as exc:
        log("answer callback failed: {}".format(exc))
        return False


def send_debug(text):
    if TG_CHAT_DEBUG:
        return send_telegram(text, chat_id=TG_CHAT_DEBUG)
    return False


def send_telegram_photo(image_bytes, caption, chat_id=None):
    url = "https://api.telegram.org/bot{}/sendPhoto".format(TG_TOKEN)
    try:
        r = requests.post(
            url,
            data={
                "chat_id": chat_id or TG_CHAT,
                "caption": caption,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            files={"photo": ("card.png", image_bytes, "image/png")},
            timeout=30,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        log("TG photo failed: {}".format(exc))
        return False


def send_notification(text, image_bytes=None, chat_id=None):
    if image_bytes and send_telegram_photo(image_bytes, text, chat_id=chat_id):
        return True
    return send_telegram(text, chat_id=chat_id)


def empty_state():
    return {
        "fortress": {
            "had": False,
            "name": None,
            "id": None,
            "last_attackers": [],
            "owner_image": None,
            "last_siege_at": 0,
            "notified_siege": False,
            "notified_lost": False,
            "siege_first_notify": 0,
            "notified_reminder": False,
        },
        "castle": {
            "had": False,
            "name": None,
            "id": None,
            "last_attackers": [],
            "owner_image": None,
            "last_siege_at": 0,
            "notified_siege": False,
            "notified_lost": False,
            "siege_first_notify": 0,
            "notified_reminder": False,
        },
        "our_fortress_attacks": {},
        "our_castle_attacks": {},
        "news": {
            "last_seen_id": 0,
            "sent_ids": [],
            "pending": [],
        },
        "forum_news": {
            "last_seen_id": 0,
            "sent_ids": [],
            "pending": [],
        },
        "meta": {
            "backoff_until": {},
            "last_alerts": {},
        },
    }


def load_state():
    state = None
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            try:
                state = json.load(fh)
            except Exception:
                state = None
    else:
        state = None

    if not isinstance(state, dict):
        state = empty_state()

    default_state = empty_state()
    for key, value in default_state.items():
        if key not in state:
            state[key] = value
        elif isinstance(value, dict) and isinstance(state.get(key), dict):
            for nested_key, nested_value in value.items():
                if nested_key not in state[key]:
                    state[key][nested_key] = nested_value

    if "meta" not in state:
        state["meta"] = {"backoff_until": {}, "last_alerts": {}}
    if "backoff_until" not in state["meta"]:
        state["meta"]["backoff_until"] = {}
    if "last_alerts" not in state["meta"]:
        state["meta"]["last_alerts"] = {}
    return state


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def random_prewait(label):
    delay = random.randint(*PRE_FETCH_DELAY)
    log("{} pre-wait {}s".format(label, delay))
    time.sleep(delay)


def should_backoff(state, page_key):
    until = state["meta"]["backoff_until"].get(page_key, 0)
    now = int(time.time())
    if until and now < until:
        log("{} skipped due to backoff until {}".format(page_key, until))
        return True
    return False


def set_backoff(state, page_key, minutes):
    state["meta"]["backoff_until"][page_key] = int(time.time()) + minutes * 60


def clear_backoff(state, page_key):
    state["meta"]["backoff_until"].pop(page_key, None)


def fetch_channel_posts(channel_url):
    try:
        response = requests.get(channel_url, timeout=20)
        response.raise_for_status()
    except Exception as exc:
        log("channel fetch failed: {}".format(exc))
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    posts = []
    for wrap in soup.select("div.tgme_widget_message_wrap"):
        link = wrap.select_one("a.tgme_widget_message_date")
        text_node = wrap.select_one("div.tgme_widget_message_text")
        if not link or not text_node:
            continue
        href = link.get("href") or ""
        match = re.search(r"/([^/]+)/([0-9]+)(?:\?|$)", href)
        if not match:
            continue
        post_id = int(match.group(2))
        text = text_node.get_text("\n", strip=True)
        if not text:
            continue
        posts.append({
            "id": post_id,
            "url": href,
            "text": text,
        })
    posts.sort(key=lambda item: item["id"])
    return posts


def fetch_forum_posts(forum_url):
    try:
        response = requests.get(forum_url, timeout=25, headers={"User-Agent": USER_AGENTS[0]})
        response.raise_for_status()
    except Exception as exc:
        log("forum fetch failed: {}".format(exc))
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    posts = []
    for article in soup.select("article.message"):
        article_id = article.get("data-content") or article.get("id") or ""
        match = re.search(r"post-?(\d+)", article_id)
        if not match:
            continue
        post_id = int(match.group(1))
        body_node = article.select_one("div.bbWrapper")
        if not body_node:
            continue
        text = body_node.get_text("\n", strip=True)
        if not text:
            continue
        posts.append({
            "id": post_id,
            "url": "{}#post-{}".format(forum_url.split("?")[0], post_id),
            "text": text,
            "source": "forum",
        })
    posts.sort(key=lambda item: item["id"])
    return posts


def gemini_rewrite_x1000_news(text):
    if not GEMINI_API_KEY:
        return None

    prompt = (
        "Ти редактор новин для українського Telegram-каналу клану в MMORPG Scryde.\n"
        "Завдання: проаналізуй новину російською мовою та визнач, чи стосується вона сервера x1000.\n"
        "Потрібно враховувати тільки сервер x1000. Якщо новина стосується лише інших серверів, турнірів, стримів, загальних активностей без прив'язки до x1000, відповідай що вона не релевантна.\n"
        "Якщо новина частково стосується кількох серверів, залиш тільки частину, яка стосується x1000.\n"
        "Прибери зайве: інформацію про інші сервери, рекламні вставки, посилання на стріми, зайві CTA, фрази про підписку, другорядний шум.\n"
        "Переклади результат українською мовою і поверни вже ГОТОВИЙ HTML для Telegram.\n"
        "Використовуй тільки сумісні з Telegram HTML теги: <b>, <i>, <code>, <a>.\n"
        "Якщо є промокод, обов'язково загорни його в <code>.\n"
        "Збережи красиве форматування по контексту: абзаци, списки, акценти. Не вигадуй інформацію, якої нема в оригіналі.\n"
        "\n"
        "Поверни JSON об'єкт такого вигляду:\n"
        "{{\"relevant\": true|false, \"title\": \"короткий заголовок\", \"text\": \"готовий HTML для Telegram\"}}\n"
        "Без markdown-обгорток, без пояснень, лише JSON.\n"
        "\n"
        "Оригінальна новина:\n{}"
    ).format(text)

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part.from_text(text=prompt)],
                )
            ],
            config=types.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json",
                thinking_config=types.ThinkingConfig(thinking_level=GEMINI_THINKING_LEVEL),
                safety_settings=[
                    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
                    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
                ],
            ),
        )
        text_out = response.text
        parsed = json.loads(text_out)
        if not isinstance(parsed, dict):
            return None
        parsed["relevant"] = bool(parsed.get("relevant", False))
        parsed["title"] = str(parsed.get("title", "") or "").strip()
        parsed["text"] = str(parsed.get("text", "") or "").strip()
        return parsed
    except Exception as exc:
        log("gemini rewrite failed: {}".format(exc))
        send_debug(DEBUG_CYCLE_ERROR.format(error="gemini news error: {}".format(str(exc)[:240])))
        return None


def process_channel_news(state):
    posts = fetch_channel_posts(SCRYDE_CHANNEL_URL)
    if not posts:
        return

    if NEWS_TEST_POST_IDS:
        post_map = {post["id"]: post for post in posts}
        for post_id in NEWS_TEST_POST_IDS:
            post = post_map.get(post_id)
            if not post:
                send_debug(DEBUG_CYCLE_ERROR.format(error="news test post not found: {}".format(post_id)))
                continue
            rewritten = gemini_rewrite_x1000_news(post["text"])
            if not rewritten:
                continue
            body = (rewritten.get("text") or "НЕ РЕЛЕВАНТНО").strip()
            relevance = "true" if rewritten.get("relevant") else "false"
            message = "<b>[NEWS TEST MANUAL]</b>\n\nrelevant: <code>{}</code>\n\n{}\n\n{}".format(relevance, body, post["url"])
            send_telegram(message, chat_id=TG_CHAT_DEBUG or None)
        return

    process_feed_posts(state, posts, "news", "telegram")


def process_forum_news(state):
    posts = fetch_forum_posts(SCRYDE_FORUM_UPDATES_URL)
    if not posts:
        return

    process_feed_posts(state, posts, "forum_news", "forum")


def process_feed_posts(state, posts, state_key, source_label):
    if not posts:
        return

    news_state = state.setdefault(state_key, {"last_seen_id": 0, "sent_ids": [], "pending": []})
    last_seen_id = int(news_state.get("last_seen_id", 0) or 0)
    sent_ids = set(news_state.get("sent_ids", []))

    if last_seen_id <= 0:
        news_state["last_seen_id"] = max(post["id"] for post in posts)
        log("{} warm start, stored last_seen_id={}".format(source_label, news_state["last_seen_id"]))
        return

    new_posts = [post for post in posts if post["id"] > last_seen_id]
    if not new_posts:
        return

    for post in new_posts:
        rewritten = gemini_rewrite_x1000_news(post["text"])
        news_state["last_seen_id"] = max(news_state.get("last_seen_id", 0), post["id"])
        if not rewritten or not rewritten.get("relevant"):
            continue
        if post["id"] in sent_ids:
            continue

        title = (rewritten.get("title") or "Новина Scryde x1000").strip()
        body = (rewritten.get("text") or "").strip()
        if not body:
            continue

        pending_item = {
            "post_id": post["id"],
            "title": title,
            "text": body,
            "url": post["url"],
            "created_at": int(time.time()),
            "publish_after": int(time.time()) + NEWS_APPROVE_DELAY_MIN * 60,
            "status": "pending",
            "debug_message_id": None,
            "source": source_label,
        }

        if TG_CHAT_DEBUG:
            buttons = {
                "inline_keyboard": [[
                    {"text": "Запостити зараз", "callback_data": "news:publish:{}:{}".format(state_key, post["id"])},
                    {"text": "Скасувати", "callback_data": "news:cancel:{}:{}".format(state_key, post["id"])},
                ]]
            }
            if NEWS_TARGET_CHAT == "debug":
                footer = "Автопублікація: <b>вимкнена (debug mode)</b>"
            else:
                footer = "Автопублікація через <b>{} хв</b>".format(NEWS_APPROVE_DELAY_MIN)
            preview = "<b>[{} PENDING]</b> <b>{}</b>\n\n{}\n\n{}\n\n{}".format(source_label.upper(), title, body, footer, post["url"])
            pending_item["debug_message_id"] = send_telegram_with_markup(preview, buttons, chat_id=TG_CHAT_DEBUG)

        news_state.setdefault("pending", []).append(pending_item)
        sent_ids.add(post["id"])

    news_state["sent_ids"] = sorted(sent_ids)[-50:]
    news_state["pending"] = news_state.get("pending", [])[-50:]


def process_pending_news_queue(state):
    now = int(time.time())
    for state_key in ("news", "forum_news"):
        news_state = state.setdefault(state_key, {"last_seen_id": 0, "sent_ids": [], "pending": []})
        pending_items = news_state.get("pending", [])

        for item in pending_items:
            if item.get("status") != "pending":
                continue
            if NEWS_TARGET_CHAT == "debug":
                continue
            if now < int(item.get("publish_after", 0) or 0):
                continue

            message = "<b>{}</b>\n\n{}\n\n{}".format(item.get("title", "Новина Scryde x1000"), item.get("text", ""), item.get("url", ""))
            sent_ok = send_telegram(message, chat_id=TG_CHAT)
            if sent_ok:
                item["status"] = "published"
                if item.get("debug_message_id") and TG_CHAT_DEBUG:
                    edit_telegram_reply_markup(TG_CHAT_DEBUG, item["debug_message_id"])
                    send_telegram("<b>[NEWS PUBLISHED AUTO]</b> <b>{}</b>\n\n{}".format(item.get("title", "Новина"), item.get("url", "")), chat_id=TG_CHAT_DEBUG)


def handle_news_callback(state, callback):
    data = callback.get("data") or ""
    if not data.startswith("news:"):
        return False

    callback_id = callback.get("id")
    message = callback.get("message") or {}
    parts = data.split(":", 3)
    if len(parts) != 4 or not parts[3].isdigit():
        answer_callback_query(callback_id, "Некоректна дія")
        return True

    action = parts[1]
    state_key = parts[2]
    post_id = int(parts[3])
    news_state = state.setdefault(state_key, {"last_seen_id": 0, "sent_ids": [], "pending": []})
    item = next((x for x in news_state.get("pending", []) if int(x.get("post_id", 0)) == post_id and x.get("status") == "pending"), None)
    if not item:
        answer_callback_query(callback_id, "Пост уже оброблений")
        return True

    if action == "cancel":
        item["status"] = "cancelled"
        edit_telegram_reply_markup(message.get("chat", {}).get("id"), message.get("message_id"))
        answer_callback_query(callback_id, "Скасовано")
        return True

    if action == "publish":
        outgoing = "<b>{}</b>\n\n{}\n\n{}".format(item.get("title", "Новина Scryde x1000"), item.get("text", ""), item.get("url", ""))
        sent_ok = send_telegram(outgoing, chat_id=TG_CHAT)
        if sent_ok:
            item["status"] = "published"
            edit_telegram_reply_markup(message.get("chat", {}).get("id"), message.get("message_id"))
            answer_callback_query(callback_id, "Опубліковано")
        else:
            answer_callback_query(callback_id, "Не вдалося опублікувати")
        return True

    answer_callback_query(callback_id, "Невідома дія")
    return True


def process_callback_updates(state):
    url = "https://api.telegram.org/bot{}/getUpdates".format(TG_TOKEN)
    meta = state.setdefault("meta", {})
    offset = int(meta.get("tg_update_offset", 0) or 0)
    try:
        response = requests.get(
            url,
            params={
                "offset": offset,
                "timeout": 0,
                "allowed_updates": json.dumps(["callback_query"]),
            },
            timeout=20,
        )
        response.raise_for_status()
        updates = response.json().get("result", [])
    except Exception as exc:
        log("getUpdates callback fetch failed: {}".format(exc))
        return

    max_update_id = None
    for update in updates:
        max_update_id = update.get("update_id")
        callback = update.get("callback_query")
        if callback:
            handle_news_callback(state, callback)

    if max_update_id is not None:
        meta["tg_update_offset"] = max_update_id + 1


def build_siege_alert_key(obj_key, obj_id, siege_at, attackers):
    attacker_names = sorted(
        a if isinstance(a, str) else a.get("name", "")
        for a in attackers
    )
    return "{}:{}:{}:{}".format(obj_key, obj_id, siege_at or 0, "|".join(attacker_names))


def should_send_siege_alert(state, alert_key, now, ttl_seconds=3 * 60 * 60):
    last_alerts = state.get("meta", {}).get("last_alerts", {})
    last_ts = last_alerts.get(alert_key, 0)
    return not last_ts or (now - last_ts) > ttl_seconds


def remember_siege_alert(state, alert_key, now, max_entries=50):
    last_alerts = state.setdefault("meta", {}).setdefault("last_alerts", {})
    last_alerts[alert_key] = now
    stale_before = now - 24 * 60 * 60
    for key in list(last_alerts.keys()):
        if last_alerts[key] < stale_before:
            del last_alerts[key]
    if len(last_alerts) > max_entries:
        for key, _ in sorted(last_alerts.items(), key=lambda item: item[1])[:-max_entries]:
            del last_alerts[key]


def fetch_page_data(url, page_key, state):
    if should_backoff(state, page_key):
        return None

    random_prewait(page_key)

    html = ""
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=random.choice(USER_AGENTS),
            locale="uk-UA",
            viewport={"width": 1366, "height": 768},
        )
        page = context.new_page()
        page.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "font", "media", "stylesheet"}
            else route.continue_(),
        )
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_selector("script#__NEXT_DATA__", timeout=15000)
            except PlaywrightTimeoutError:
                page.wait_for_timeout(4000)
            html = page.content()
        finally:
            browser.close()

    soup = BeautifulSoup(html, "html.parser")
    script_tag = soup.find("script", id="__NEXT_DATA__")
    if not script_tag or not script_tag.string:
        _challenge_counts[page_key] += 1
        log("{} anti-bot/no data, count={}".format(page_key, _challenge_counts[page_key]))
        if _challenge_counts[page_key] >= 1:
            set_backoff(state, page_key, BACKOFF_MINUTES_ON_CHALLENGE)
        _error_counts[page_key] += 1
        if _error_counts[page_key] == SITE_ERROR_NOTIFY_AFTER:
            send_debug(DEBUG_SITE_DOWN.format(page=page_key, count=_error_counts[page_key], url=url))
        return None

    clear_backoff(state, page_key)
    if _error_counts[page_key] >= SITE_ERROR_NOTIFY_AFTER:
        send_debug(DEBUG_SITE_UP.format(page=page_key))
    _error_counts[page_key] = 0
    _challenge_counts[page_key] = 0

    data = json.loads(script_tag.string)
    log("{} loaded {} objects".format(page_key, len(data["props"]["pageProps"]["rankingRows"]["items"])))
    return data["props"]["pageProps"]["rankingRows"]["items"]


def get_attackers(item):
    siege_sides = item.get("siege_sides", [])
    if not siege_sides or isinstance(siege_sides, list):
        return []
    return [a["name"] for a in siege_sides.get("attackers", []) if "name" in a]


def format_time(ts):
    if not ts:
        return "невідомо"
    try:
        return datetime.fromtimestamp(ts, tz=GAME_TZ).strftime("%d.%m %H:%M")
    except Exception:
        return str(ts)


def build_event_card(obj_type, obj_name, event_text, event_color, owner_name, owner_icon_url, attackers, siege_time, page_url):
    if not CARDS_ENABLED:
        return None
    try:
        return build_card(
            obj_type=obj_type,
            obj_name=obj_name,
            event_text=event_text,
            event_color=event_color,
            owner_name=owner_name,
            owner_icon_url=owner_icon_url,
            attackers=attackers,
            siege_time=siege_time,
            page_url=page_url,
        )
    except Exception as exc:
        log("build_card failed: {}".format(exc))
        return None


def process_defence(state_section, items, obj_key, page_url):
    o = OBJ[obj_key]
    obj_type = o["acc"]
    s = state_section
    our = None
    for item in items:
        owner = item.get("owner")
        if owner and owner.get("name") == OUR_CLAN:
            our = item
            break

    if our:
        fort_name = our["name"]
        fort_id = our["id"]
        attackers = get_attackers(our)
        siege_at = our.get("siege_at", 0)

        if not s["had"]:
            s["had"] = True
            s["name"] = fort_name
            s["id"] = fort_id
            s["notified_lost"] = False
            s["notified_siege"] = False
            s["last_attackers"] = []
            s["last_siege_at"] = 0

        s["name"] = fort_name
        s["id"] = fort_id
        s["owner_image"] = (our.get("owner") or {}).get("image")
        s["notified_lost"] = False

        if attackers and siege_at:
            now = int(time.time())
            attackers_str = ", ".join(attackers)
            siege_time_str = format_time(siege_at)
            alert_key = build_siege_alert_key(obj_key, fort_id, siege_at, attackers)
            cur_names = sorted(a if isinstance(a, str) else a.get("name", "") for a in attackers)
            prev_names = sorted(a if isinstance(a, str) else a.get("name", "") for a in s.get("last_attackers", []))
            new_attackers = cur_names != prev_names
            new_siege_time = siege_at != s.get("last_siege_at", 0)
            mins_left = (siege_at - now) // 60

            should_notify = (not s["notified_siege"]) or new_attackers or new_siege_time
            if should_notify and not should_send_siege_alert(state_section.get("_root_state", {}), alert_key, now):
                log("skip duplicate siege alert {}".format(alert_key))
                s["notified_siege"] = True
                atk_list = (our.get("siege_sides") or {}).get("attackers", [])
                s["last_attackers"] = [{"name": a.get("name", "?"), "image": a.get("image")} for a in atk_list]
                s["last_siege_at"] = siege_at
                should_notify = False

            if should_notify:
                msg = SIEGE_ATTACK.format(
                    our_acc=o["our_acc"],
                    nom=o["nom"],
                    name=fort_name,
                    attackers=attackers_str,
                    time=siege_time_str,
                    url=page_url,
                )
                image = build_event_card(
                    obj_type,
                    fort_name,
                    "Атакують {}!".format(o["our_acc"]),
                    C_RED,
                    OUR_CLAN,
                    (our.get("owner") or {}).get("image"),
                    (our.get("siege_sides") or {}).get("attackers", []),
                    siege_time_str,
                    page_url,
                )
                if send_notification(msg, image):
                    if not s["notified_siege"]:
                        s["siege_first_notify"] = now
                        s["notified_reminder"] = False
                    s["notified_siege"] = True
                    atk_list = (our.get("siege_sides") or {}).get("attackers", [])
                    s["last_attackers"] = [{"name": a.get("name", "?"), "image": a.get("image")} for a in atk_list]
                    s["last_siege_at"] = siege_at
                    remember_siege_alert(state_section.get("_root_state", {}), alert_key, now)

            first_notify = s.get("siege_first_notify", 0)
            time_since_first = now - first_notify if first_notify else 0
            if s["notified_siege"] and not s.get("notified_reminder") and 0 < mins_left <= 25 and time_since_first >= 90 * 60:
                msg = SIEGE_REMINDER.format(
                    our_acc=o["our_acc"],
                    nom=o["nom"],
                    mins=max(0, mins_left),
                    name=fort_name,
                    attackers=attackers_str,
                    time=siege_time_str,
                    url=page_url,
                )
                image = build_event_card(
                    obj_type,
                    fort_name,
                    "Облога {} через {} хв!".format(o["our_acc"], max(0, mins_left)),
                    C_GOLD,
                    OUR_CLAN,
                    (our.get("owner") or {}).get("image"),
                    (our.get("siege_sides") or {}).get("attackers", []),
                    siege_time_str,
                    page_url,
                )
                if send_notification(msg, image):
                    s["notified_reminder"] = True

        elif not attackers and s.get("notified_siege"):
            now = int(time.time())
            last_siege_at = s.get("last_siege_at", 0)
            if not (last_siege_at and now >= last_siege_at):
                msg = SIEGE_CANCELLED.format(our_acc=o["our_acc"], nom=o["nom"], name=fort_name, url=page_url)
                image = build_event_card(obj_type, fort_name, "Атаку відмінено", (60, 60, 80), OUR_CLAN, s.get("owner_image"), [], None, page_url)
                send_notification(msg, image)
            s["notified_siege"] = False
            s["last_attackers"] = []
            s["last_siege_at"] = 0
            s["siege_first_notify"] = 0
            s["notified_reminder"] = False
    else:
        if s["had"] and not s.get("notified_lost"):
            fort_name = s.get("name") or "невідомий об'єкт"
            our_old = next((f for f in items if f.get("id") == s.get("id")), None)
            if our_old:
                new_owner = our_old.get("owner")
                new_owner_name = "NPC (без власника)" if new_owner is None else new_owner.get("name", "невідомо")
            else:
                new_owner_name = "невідомо"
            msg = OBJECT_LOST.format(acc_lost=o["acc_lost"], nom=o["nom"], name=fort_name, owner=new_owner_name, url=page_url)
            image = build_event_card(obj_type, fort_name, "{} втрачено!".format(o["acc_lost"]), (80, 80, 80), new_owner_name, (our_old.get("owner") or {}).get("image") if our_old else None, [], None, page_url)
            if send_notification(msg, image):
                s["had"] = False
                s["notified_lost"] = True
                s["notified_siege"] = False
                s["last_attackers"] = []
                s["last_siege_at"] = 0
                s["siege_first_notify"] = 0
                s["notified_reminder"] = False
            else:
                s["had"] = False
    return s


def process_our_attacks(attack_state, items, obj_key, page_url):
    o = OBJ[obj_key]
    obj_type = o["acc"]
    current_ids = set()

    for item in items:
        attackers = get_attackers(item)
        if OUR_CLAN not in attackers:
            continue
        owner = item.get("owner")
        if owner and owner.get("name") == OUR_CLAN:
            continue

        obj_id = str(item["id"])
        obj_name = item["name"]
        siege_at = item.get("siege_at", 0)
        owner_name = owner["name"] if owner else "NPC"
        siege_sides = item.get("siege_sides") or {}
        attacker_rows = siege_sides.get("attackers", []) if isinstance(siege_sides, dict) else []
        siege_time_str = format_time(siege_at)
        current_ids.add(obj_id)
        prev = attack_state.get(obj_id, {})

        if not prev.get("notified") or siege_at != prev.get("siege_at", 0):
            msg = WE_ATTACK.format(acc=o["acc"], nom=o["nom"], name=obj_name, owner=owner_name, time=siege_time_str, url=page_url)
            image = build_event_card(
                obj_type,
                obj_name,
                "Атакуємо {}!".format(o["acc"]),
                (26, 107, 138),
                owner_name,
                (item.get("owner") or {}).get("image"),
                attacker_rows,
                siege_time_str,
                page_url,
            )
            if send_notification(msg, image):
                attack_state[obj_id] = {
                    "name": obj_name,
                    "siege_at": siege_at,
                    "notified": True,
                    "owner_icon": (item.get("owner") or {}).get("image"),
                }

    disappeared = set(attack_state.keys()) - current_ids
    now = int(time.time())
    to_delete = []
    for obj_id in disappeared:
        prev = attack_state[obj_id]
        obj_name = prev.get("name", "невідомо")
        siege_at = prev.get("siege_at", 0)
        if siege_at and now >= siege_at:
            to_delete.append(obj_id)
        else:
            msg = WE_CANCELLED.format(nom=o["nom"], name=obj_name)
            if send_telegram(msg):
                to_delete.append(obj_id)

    for obj_id in to_delete:
        del attack_state[obj_id]

    return attack_state


def main():
    state = load_state()
    process_callback_updates(state)
    state["fortress"]["_root_state"] = state
    state["castle"]["_root_state"] = state
    process_channel_news(state)
    process_forum_news(state)
    process_pending_news_queue(state)
    fortress_items = fetch_page_data(FORTRESS_URL, "fortresses", state)
    delay = random.randint(*BETWEEN_REQUESTS_DELAY)
    log("between requests delay {}s".format(delay))
    time.sleep(delay)
    castle_items = fetch_page_data(CASTLE_URL, "castles", state)

    if fortress_items is not None:
        state["fortress"] = process_defence(state["fortress"], fortress_items, "fortress", FORTRESS_URL)
        state["our_fortress_attacks"] = process_our_attacks(state.get("our_fortress_attacks", {}), fortress_items, "fortress", FORTRESS_URL)

    if castle_items is not None:
        state["castle"] = process_defence(state["castle"], castle_items, "castle", CASTLE_URL)
        state["our_castle_attacks"] = process_our_attacks(state.get("our_castle_attacks", {}), castle_items, "castle", CASTLE_URL)

    state["fortress"].pop("_root_state", None)
    state["castle"].pop("_root_state", None)
    save_state(state)
    log("run complete")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_debug(DEBUG_CYCLE_ERROR.format(error=str(exc)[:300]))
        raise
