#!/usr/bin/env python3

import json
import os
import random
import re
import time
import html as html_lib
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
    from playwright.sync_api import Error as PlaywrightError
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
FORUM_TEST_POST_IDS = [int(x) for x in os.environ.get("FORUM_TEST_POST_IDS", "").split(",") if x.strip().isdigit()]
NEWS_APPROVE_DELAY_MIN = int(os.environ.get("NEWS_APPROVE_DELAY_MIN", "25"))
NEWS_PENDING_EXPIRE_HOURS = int(os.environ.get("NEWS_PENDING_EXPIRE_HOURS", "24"))
NEWS_MAX_NEW_POSTS_PER_RUN = int(os.environ.get("NEWS_MAX_NEW_POSTS_PER_RUN", "5"))
NEWS_DEBUG_PREVIEW_VERSION = 5
RUN_NEWS = os.environ.get("RUN_NEWS", "true").lower() == "true"
RUN_SIEGES = os.environ.get("RUN_SIEGES", "true").lower() == "true"
OUR_CLAN = os.environ.get("OUR_CLAN", "BSOE")
FORTRESS_URL = os.environ.get("FORTRESS_URL", "https://ua.scryde.game/rankings/1000/fortresses")
CASTLE_URL = os.environ.get("CASTLE_URL", "https://ua.scryde.game/rankings/1000/castles")
SCRYDE_CHANNEL_URL = os.environ.get("SCRYDE_CHANNEL_URL", "https://t.me/s/scryde")
SCRYDE_FORUM_UPDATES_URL = os.environ.get("SCRYDE_FORUM_UPDATES_URL", "https://board.scryde.net/threads/obnovlenija.30694/page-19")
STATE_FILE = os.environ.get("STATE_FILE", "site_state.json")

BETWEEN_REQUESTS_DELAY = (4, 9)
PRE_FETCH_DELAY = (8, 20)
BACKOFF_MINUTES_ON_CHALLENGE = int(os.environ.get("BACKOFF_MINUTES_ON_CHALLENGE", "0"))
SITE_ERROR_NOTIFY_AFTER = 2
FORTRESS_ANTIBOT_RETRIES = int(os.environ.get("FORTRESS_ANTIBOT_RETRIES", "1"))
CASTLE_ANTIBOT_RETRIES = int(os.environ.get("CASTLE_ANTIBOT_RETRIES", "1"))
DEBUG_SCRYDE_FETCH = os.environ.get("DEBUG_SCRYDE_FETCH", "false").lower() == "true"
SIEGE_DIAG_DIR = os.environ.get("SIEGE_DIAG_DIR", "siege_diagnostics")
GAME_TZ = ZoneInfo("Europe/Kyiv")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

_error_counts = {"fortresses": 0, "castles": 0}
_challenge_counts = {"fortresses": 0, "castles": 0}

TELEGRAM_ALLOWED_TAGS = {"b", "i", "code", "a", "tg-spoiler"}
TELEGRAM_TAG_RENAMES = {"strong": "b", "em": "i"}
TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_SAFE_LIMIT = 3900
TELEGRAM_SPOILER_MAX_CHARS = 120
TELEGRAM_SPOILER_MAX_RATIO = 0.18
TELEGRAM_SPOILER_RATIO_MIN_CHARS = 60


def log(msg):
    print("{} {}".format(datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def compact_text(value, limit=500):
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) > limit:
        return value[:limit] + "..."
    return value


def build_news_post_message(title, body, url):
    content = (body or "").strip() or (title or "Новина Scryde x1000")
    return "{}\n\n{}".format(content, url or "")


def truncate_telegram_text(text, limit=TELEGRAM_SAFE_LIMIT):
    text = text or ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 40)].rstrip() + "\n\n<i>…текст обрізано</i>"


def html_to_plain_text(text, limit=TELEGRAM_SAFE_LIMIT):
    soup = BeautifulSoup(text or "", "html.parser")
    plain = soup.get_text("\n", strip=True)
    plain = re.sub(r"\n{3,}", "\n\n", plain).strip()
    if len(plain) > limit:
        plain = plain[: max(0, limit - 20)].rstrip() + "\n\n…текст обрізано"
    return plain


def sanitize_telegram_html(text, limit=TELEGRAM_SAFE_LIMIT):
    soup = BeautifulSoup(text or "", "html.parser")

    for br in soup.find_all("br"):
        br.replace_with("\n")

    total_visible_len = len(re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip())

    for spoiler in soup.find_all("tg-spoiler"):
        spoiler_len = len(re.sub(r"\s+", " ", spoiler.get_text(" ", strip=True)).strip())
        spoiler_ratio = (spoiler_len / total_visible_len) if total_visible_len else 0
        if spoiler_len > TELEGRAM_SPOILER_MAX_CHARS or (spoiler_len > TELEGRAM_SPOILER_RATIO_MIN_CHARS and spoiler_ratio > TELEGRAM_SPOILER_MAX_RATIO):
            spoiler.unwrap()

    for tag in soup.find_all(True):
        name = (tag.name or "").lower()
        if name in TELEGRAM_TAG_RENAMES:
            tag.name = TELEGRAM_TAG_RENAMES[name]
            name = tag.name

        if name in {"p", "div", "section", "article", "ul", "ol", "li", "blockquote"}:
            tag.insert_before("\n")
            tag.insert_after("\n")
            tag.unwrap()
            continue

        if name not in TELEGRAM_ALLOWED_TAGS:
            tag.unwrap()
            continue

        if name == "a":
            href = (tag.get("href") or "").strip()
            if not href.startswith(("http://", "https://", "tg://")):
                tag.unwrap()
                continue
            tag.attrs = {"href": href}
        else:
            tag.attrs = {}

    cleaned = soup.decode(formatter="minimal")
    cleaned = re.sub(r"\n[ \t]+", "\n", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return truncate_telegram_text(cleaned, limit=limit)


def telegram_error_detail(response):
    if response is None:
        return ""
    try:
        return compact_text(response.text, 500)
    except Exception:
        return ""


def send_telegram(text, retries=3, chat_id=None):
    url = "https://api.telegram.org/bot{}/sendMessage".format(TG_TOKEN)
    safe_text = sanitize_telegram_html(text)
    payload = {
        "chat_id": chat_id or TG_CHAT,
        "text": safe_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=20)
            if r.ok:
                return True
            log("TG send failed {}/{}: status={} body={} len={}".format(attempt, retries, r.status_code, telegram_error_detail(r), len(payload.get("text", ""))))
            if r.status_code == 400 and payload.get("parse_mode") == "HTML":
                fallback_payload = dict(payload)
                fallback_payload.pop("parse_mode", None)
                fallback_payload["text"] = html_to_plain_text(text)
                fallback_response = requests.post(url, json=fallback_payload, timeout=20)
                if fallback_response.ok:
                    log("TG send recovered with plain-text fallback")
                    return True
                log("TG plain fallback failed {}/{}: status={} body={} len={}".format(attempt, retries, fallback_response.status_code, telegram_error_detail(fallback_response), len(fallback_payload.get("text", ""))))
        except Exception as exc:
            log("TG send failed {}/{}: {}".format(attempt, retries, exc))
            if attempt < retries:
                time.sleep(2 * attempt)
    return False


def send_telegram_with_markup(text, reply_markup, retries=3, chat_id=None):
    url = "https://api.telegram.org/bot{}/sendMessage".format(TG_TOKEN)
    safe_text = sanitize_telegram_html(text)
    payload = {
        "chat_id": chat_id or TG_CHAT,
        "text": safe_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=20)
            if r.ok:
                result = r.json().get("result", {})
                return result.get("message_id")
            log("TG send with markup failed {}/{}: status={} body={} len={}".format(attempt, retries, r.status_code, telegram_error_detail(r), len(payload.get("text", ""))))
            if r.status_code == 400 and payload.get("parse_mode") == "HTML":
                fallback_payload = dict(payload)
                fallback_payload.pop("parse_mode", None)
                fallback_payload["text"] = html_to_plain_text(text)
                fallback_response = requests.post(url, json=fallback_payload, timeout=20)
                if fallback_response.ok:
                    log("TG send with markup recovered with plain-text fallback")
                    result = fallback_response.json().get("result", {})
                    return result.get("message_id")
                log("TG markup plain fallback failed {}/{}: status={} body={} len={}".format(attempt, retries, fallback_response.status_code, telegram_error_detail(fallback_response), len(fallback_payload.get("text", ""))))
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


def edit_telegram_message_text(chat_id, message_id, text, reply_markup=None):
    url = "https://api.telegram.org/bot{}/editMessageText".format(TG_TOKEN)
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": sanitize_telegram_html(text),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=20)
        if r.ok:
            return True
        log("edit message text failed: status={} body={}".format(r.status_code, telegram_error_detail(r)))
        return False
    except Exception as exc:
        log("edit message text failed: {}".format(exc))
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


def escape_debug(value):
    return html_lib.escape(str(value), quote=False)


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
    if BACKOFF_MINUTES_ON_CHALLENGE <= 0:
        clear_backoff(state, page_key)
        return False
    until = state["meta"]["backoff_until"].get(page_key, 0)
    now = int(time.time())
    if until and now < until:
        log("{} skipped due to backoff until {}".format(page_key, until))
        return True
    return False


def set_backoff(state, page_key, minutes):
    if minutes <= 0:
        clear_backoff(state, page_key)
        return
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
        formatted_html = text_node.decode_contents().strip()
        posts.append({
            "id": post_id,
            "url": href,
            "text": text,
            "formatted_html": formatted_html,
        })
    posts.sort(key=lambda item: item["id"])
    log("telegram channel fetched {} posts".format(len(posts)))
    return posts


def fetch_forum_posts(forum_url):
    urls = [forum_url]
    try:
        latest_base_url = forum_url.split("?")[0].split("#")[0].rstrip("/")
        if latest_base_url.endswith("/latest"):
            latest_url = latest_base_url
        else:
            latest_url = re.sub(r"/page-\d+$", "", latest_base_url) + "/latest"
        latest_response = requests.get(latest_url, timeout=25, headers={"User-Agent": USER_AGENTS[0]})
        latest_response.raise_for_status()
        resolved_latest = latest_response.url.split("#")[0]
        if resolved_latest and resolved_latest not in urls:
            urls.append(resolved_latest)
            match = re.search(r"/page-(\d+)$", resolved_latest)
            if match and int(match.group(1)) > 1:
                prev_url = re.sub(r"/page-\d+$", "/page-{}".format(int(match.group(1)) - 1), resolved_latest)
                if prev_url not in urls:
                    urls.append(prev_url)
    except Exception as exc:
        log("forum latest discovery failed: {}".format(exc))

    posts = []
    seen = set()
    for url in urls:
        try:
            response = requests.get(url, timeout=25, headers={"User-Agent": USER_AGENTS[0]})
            response.raise_for_status()
        except Exception as exc:
            log("forum fetch failed {}: {}".format(url, exc))
            continue

        base_url = response.url.split("?")[0].split("#")[0]
        html = response.content.decode(response.apparent_encoding or "utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        for article in soup.select("article.message"):
            article_id = article.get("data-content") or article.get("id") or ""
            match = re.search(r"post-?(\d+)", article_id)
            if not match:
                continue
            post_id = int(match.group(1))
            if post_id in seen:
                continue
            body_node = article.select_one("div.bbWrapper")
            if not body_node:
                continue
            text = body_node.get_text("\n", strip=True)
            if not text:
                continue
            formatted_html = body_node.decode_contents().strip()
            seen.add(post_id)
            posts.append({
                "id": post_id,
                "url": "{}#post-{}".format(base_url, post_id),
                "text": text,
                "formatted_html": formatted_html,
                "source": "forum",
            })
    posts.sort(key=lambda item: item["id"])
    log("forum fetched {} posts from {} page(s)".format(len(posts), len(urls)))
    return posts


def gemini_rewrite_x1000_news(text, source_label=None, pending_context=None, source_html=None):
    if not GEMINI_API_KEY:
        return None

    pending_context_json = json.dumps(pending_context or [], ensure_ascii=False)
    source_html = (source_html or "").strip()
    prompt = (
        "Ти редактор новин для українського Telegram-каналу клану в MMORPG Scryde.\n"
        "Джерело поточної новини: {source_label}.\n"
        "Тобі передано і plain text, і оригінальний HTML/форматований фрагмент джерела. Перевагу треба віддавати саме оригінальній структурі та форматуванню з HTML-фрагмента.\n"
        "Завдання: проаналізуй новину російською мовою та визнач, чи стосується вона сервера x1000.\n"
        "Потрібно враховувати тільки сервер x1000. Якщо новина стосується лише інших серверів, турнірів, стримів, загальних активностей без прив'язки до x1000, відповідай що вона не релевантна.\n"
        "Якщо новина частково стосується кількох серверів, залиш тільки частину, яка стосується x1000.\n"
        "Дуже важливо: не плутай сервер Scryde X (x100) із сервером x1000. Згадка 'Scryde X', 'x100' або 'Скрайд X' сама по собі НЕ означає x1000.\n"
        "Водночас загальні новини, які явно стосуються всіх серверів або не обмежені іншим конкретним сервером, потрібно вважати релевантними для x1000.\n"
        "Якщо новина явно тільки про Scryde X/x100 або інший сервер без x1000, relevant=false. Якщо новина загальна для всіх серверів, relevant=true.\n"
        "У тебе є список уже наявних pending-новин. Якщо поточна новина по суті є тією самою новиною іншими словами, вибери action=replace і вкажи target_state_key + target_post_id для pending-новини, яку треба замінити.\n"
        "Якщо це справді нова окрема новина, action=new. Якщо її взагалі не треба постити, action=ignore.\n"
        "Прибери дубль заголовка в тілі тексту: якщо body починається тим самим заголовком, не повторюй його вдруге.\n"
        "Прибери зайве: інформацію про інші сервери, рекламні вставки, посилання на стріми, зайві CTA, фрази про підписку, другорядний шум.\n"
        "Переклади результат українською мовою і поверни вже ГОТОВИЙ HTML для Telegram.\n"
        "Використовуй тільки сумісні з Telegram HTML теги: <b>, <i>, <code>, <a>, <tg-spoiler>.\n"
        "<tg-spoiler> використовуй рідко і тільки для коротких необов'язкових деталей/сюрпризів; не ховай під спойлером важливі умови, половину поста, патчноут або основний зміст.\n"
        "Якщо є промокод, обов'язково загорни його в <code>.\n"
        "Збережи красиве форматування по контексту: абзаци, списки, акценти. Не вигадуй інформацію, якої нема в оригіналі.\n"
        "Додай трохи доречних емодзі, але без спаму: зазвичай 2-5 на весь пост.\n"
        "Якщо пост довгий і має другорядний блок, наприклад 'Новий клієнт', 'додатково', 'на інші сервери завтра', зазвичай не ховай його під спойлер: або залиш стисло відкритим текстом, або прибери як шум.\n"
        "Якщо новина важлива і структурована, намагайся зберігати оригінальну логіку секцій: короткий вступ, основний патчноут, другорядні деталі нижче.\n"
        "Фінальний текст має виглядати живіше і ближче до стилю Telegram-каналу, але без рекламного хвоста.\n"
        "\n"
        "Ось уже наявні pending-новини:\n{pending_context_json}\n"
        "\n"
        "Оригінальний форматований HTML-фрагмент джерела:\n{source_html}\n"
        "\n"
        "Поверни JSON об'єкт такого вигляду:\n"
        "{{\"relevant\": true|false, \"action\": \"new|replace|ignore\", \"target_state_key\": \"news|forum_news|\", \"target_post_id\": 0, \"title\": \"короткий заголовок\", \"text\": \"готовий HTML для Telegram\"}}\n"
        "Без markdown-обгорток, без пояснень, лише JSON.\n"
        "\n"
        "Оригінальна новина:\n{}"
    ).format(text, source_label=source_label or "unknown", pending_context_json=pending_context_json, source_html=source_html)

    client = genai.Client(api_key=GEMINI_API_KEY)
    retries = 4
    for attempt in range(1, retries + 1):
        try:
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
            parsed["action"] = str(parsed.get("action", "new") or "new").strip().lower()
            parsed["target_state_key"] = str(parsed.get("target_state_key", "") or "").strip()
            parsed["target_post_id"] = int(parsed.get("target_post_id", 0) or 0)
            parsed["title"] = str(parsed.get("title", "") or "").strip()
            parsed["text"] = str(parsed.get("text", "") or "").strip()
            return parsed
        except Exception as exc:
            err = str(exc)
            transient = any(token in err for token in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "Timeout", "timed out"))
            log("gemini rewrite failed attempt {}/{}: {}".format(attempt, retries, err))
            if transient and attempt < retries:
                time.sleep(min(20, attempt * 4))
                continue
            if not transient:
                send_debug(DEBUG_CYCLE_ERROR.format(error="gemini news error: {}".format(err[:240])))
            return None


def build_pending_context(state):
    pending_items = []
    for state_key in ("news", "forum_news"):
        news_state = state.setdefault(state_key, {"last_seen_id": 0, "sent_ids": [], "pending": []})
        for item in news_state.get("pending", []):
            if item.get("status") not in {"pending", "approved"}:
                continue
            pending_items.append({
                "state_key": state_key,
                "post_id": item.get("post_id"),
                "source": item.get("source"),
                "title": item.get("title"),
                "text": item.get("text"),
                "url": item.get("url"),
            })
    return pending_items[-10:]


def news_command_help(state_key=None, post_id=None):
    if state_key and post_id:
        return (
            "\n\n<b>Керування командами:</b>\n"
            "/news_publish {state_key} {post_id}\n"
            "/news_cancel {state_key} {post_id}\n"
            "/news_delay {state_key} {post_id} 60\n"
            "/news_show {state_key} {post_id}\n"
            "/news_retry {state_key} {post_id}\n"
            "/news_list"
        ).format(state_key=state_key, post_id=post_id)
    return (
        "<b>Керування новинами:</b>\n"
        "/news_list\n"
        "/news_show news 4650\n"
        "/news_publish news 4650\n"
        "/news_cancel news 4650\n"
        "/news_delay news 4650 60\n"
        "/news_retry news 4650"
    )


def news_preview_footer():
    controls = "Відповісти на це повідомлення: <b>+</b> опублікувати, <b>-</b> скасувати, <b>delay 60</b> відкласти"
    if NEWS_TARGET_CHAT == "debug":
        return "Автопублікація: <b>вимкнена (debug mode)</b>\n{}".format(controls)
    return "Автопублікація через <b>{} хв</b>\n{}".format(NEWS_APPROVE_DELAY_MIN, controls)


def build_pending_preview(source_label, title, body, url, updated=False):
    label = "{} PENDING{}".format(source_label.upper(), " UPDATED" if updated else "")
    content = (body or "").strip() or (title or "Новина Scryde x1000")
    return "<b>[{}]</b>\n\n{}\n\n{}\n\n{}".format(
        label,
        content,
        news_preview_footer(),
        url,
    )


def news_action_buttons(state_key, post_id):
    return {
        "inline_keyboard": [[
            {"text": "Запостити зараз", "callback_data": "news:publish:{}:{}".format(state_key, post_id)},
            {"text": "Скасувати", "callback_data": "news:cancel:{}:{}".format(state_key, post_id)},
        ], [
            {"text": "Відкласти 60 хв", "callback_data": "news:delay60:{}:{}".format(state_key, post_id)},
            {"text": "Показати", "callback_data": "news:show:{}:{}".format(state_key, post_id)},
        ]]
    }


def find_news_item(state, state_key, post_id, only_pending=False):
    news_state = state.setdefault(state_key, {"last_seen_id": 0, "sent_ids": [], "pending": []})
    for item in news_state.get("pending", []):
        if int(item.get("post_id", 0) or 0) != int(post_id):
            continue
        if only_pending and item.get("status") != "pending":
            continue
        return item
    return None


def find_moderatable_news_item(state, state_key, post_id):
    news_state = state.setdefault(state_key, {"last_seen_id": 0, "sent_ids": [], "pending": []})
    for item in news_state.get("pending", []):
        if int(item.get("post_id", 0) or 0) != int(post_id):
            continue
        if item.get("status") in {"pending", "approved"}:
            return item
    return None


def format_news_item_summary(state_key, item):
    return "{} {} [{}] — {}".format(
        state_key,
        item.get("post_id"),
        item.get("status", "unknown"),
        compact_text(item.get("title", "Новина"), 80),
    )


def format_news_item_preview(state_key, item):
    content = (item.get("text", "") or "").strip() or item.get("title", "Новина")
    return (
        "<b>[NEWS ITEM]</b>\n"
        "title: <code>{title}</code>\n"
        "state: <code>{state_key}</code>\n"
        "post_id: <code>{post_id}</code>\n"
        "status: <code>{status}</code>\n\n"
        "{text}\n\n"
        "{commands}\n\n"
        "{url}"
    ).format(
        title=item.get("title", "Новина"),
        state_key=state_key,
        post_id=item.get("post_id"),
        status=item.get("status", "unknown"),
        text=content,
        commands=news_command_help(state_key, item.get("post_id")),
        url=item.get("url", ""),
    )


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
            rewritten = gemini_rewrite_x1000_news(post["text"], source_label="telegram", source_html=post.get("formatted_html", ""))
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

    if FORUM_TEST_POST_IDS:
        post_map = {post["id"]: post for post in posts}
        for post_id in FORUM_TEST_POST_IDS:
            post = post_map.get(post_id)
            if not post:
                send_debug(DEBUG_CYCLE_ERROR.format(error="forum test post not found: {}".format(post_id)))
                continue
            rewritten = gemini_rewrite_x1000_news(post["text"], source_label="forum", source_html=post.get("formatted_html", ""))
            if not rewritten:
                continue
            body = (rewritten.get("text") or "НЕ РЕЛЕВАНТНО").strip()
            relevance = "true" if rewritten.get("relevant") else "false"
            message = "<b>[FORUM TEST MANUAL]</b>\n\nrelevant: <code>{}</code>\n\n{}\n\n{}".format(relevance, body, post["url"])
            send_telegram(message, chat_id=TG_CHAT_DEBUG or None)
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
        log("{} no new posts after last_seen_id={}".format(source_label, last_seen_id))
        return

    if NEWS_MAX_NEW_POSTS_PER_RUN > 0 and len(new_posts) > NEWS_MAX_NEW_POSTS_PER_RUN:
        skipped = len(new_posts) - NEWS_MAX_NEW_POSTS_PER_RUN
        log("{} backlog has {} new posts; skipping {} older posts and processing latest {}".format(source_label, len(new_posts), skipped, NEWS_MAX_NEW_POSTS_PER_RUN))
        new_posts = new_posts[-NEWS_MAX_NEW_POSTS_PER_RUN:]

    log("{} processing {} new posts after last_seen_id={}".format(source_label, len(new_posts), last_seen_id))

    for post in new_posts:
        rewritten = gemini_rewrite_x1000_news(
            post["text"],
            source_label=source_label,
            pending_context=build_pending_context(state),
            source_html=post.get("formatted_html", ""),
        )
        news_state["last_seen_id"] = max(news_state.get("last_seen_id", 0), post["id"])
        if not rewritten or not rewritten.get("relevant"):
            continue
        if post["id"] in sent_ids:
            continue

        title = (rewritten.get("title") or "Новина Scryde x1000").strip()
        body = (rewritten.get("text") or "").strip()
        if not body:
            continue
        title_prefix = "⚙️ " if source_label == "forum" else ""
        display_title = "{}{}".format(title_prefix, title)

        if rewritten.get("action") == "replace" and rewritten.get("target_state_key") in {"news", "forum_news"} and rewritten.get("target_post_id"):
            target_state = state.setdefault(rewritten["target_state_key"], {"last_seen_id": 0, "sent_ids": [], "pending": []})
            target_item = next((x for x in target_state.get("pending", []) if int(x.get("post_id", 0)) == int(rewritten.get("target_post_id")) and x.get("status") in {"pending", "approved"}), None)
            if target_item:
                target_item["title"] = display_title
                target_item["text"] = body
                target_item["url"] = post["url"]
                target_item["source"] = source_label
                target_item["debug_preview_version"] = NEWS_DEBUG_PREVIEW_VERSION
                if target_item.get("debug_message_id") and TG_CHAT_DEBUG:
                    preview = build_pending_preview(source_label, display_title, body, post["url"], updated=True)
                    target_item["debug_message_id"] = send_telegram_with_markup(preview, None, chat_id=TG_CHAT_DEBUG)
                sent_ids.add(post["id"])
                continue

        if rewritten.get("action") == "ignore":
            sent_ids.add(post["id"])
            continue

        pending_item = {
            "post_id": post["id"],
            "title": display_title,
            "text": body,
            "url": post["url"],
            "created_at": int(time.time()),
            "publish_after": int(time.time()) + NEWS_APPROVE_DELAY_MIN * 60,
            "status": "pending",
            "debug_message_id": None,
            "debug_preview_version": NEWS_DEBUG_PREVIEW_VERSION,
            "source": source_label,
        }

        if TG_CHAT_DEBUG:
            preview = build_pending_preview(source_label, display_title, body, post["url"])
            pending_item["debug_message_id"] = send_telegram_with_markup(preview, None, chat_id=TG_CHAT_DEBUG)

        news_state.setdefault("pending", []).append(pending_item)
        sent_ids.add(post["id"])

    news_state["sent_ids"] = sorted(sent_ids)[-50:]
    news_state["pending"] = news_state.get("pending", [])[-50:]


def process_pending_news_queue(state):
    now = int(time.time())
    expire_before = now - NEWS_PENDING_EXPIRE_HOURS * 60 * 60
    for state_key in ("news", "forum_news"):
        news_state = state.setdefault(state_key, {"last_seen_id": 0, "sent_ids": [], "pending": []})
        pending_items = news_state.get("pending", [])

        for item in pending_items:
            status = item.get("status")
            if status not in {"pending", "approved"}:
                continue
            if status == "pending" and int(item.get("created_at", 0) or 0) < expire_before:
                item["status"] = "expired"
                log("{} pending post {} expired without publishing".format(state_key, item.get("post_id")))
                continue
            if NEWS_TARGET_CHAT == "debug":
                continue
            if now < int(item.get("publish_after", 0) or 0):
                continue

            message = build_news_post_message(item.get("title", "Новина Scryde x1000"), item.get("text", ""), item.get("url", ""))
            sent_ok = send_telegram(message, chat_id=TG_CHAT)
            if sent_ok:
                item["status"] = "published"
                log("{} pending post {} published".format(state_key, item.get("post_id")))
                if item.get("debug_message_id") and TG_CHAT_DEBUG:
                    edit_telegram_reply_markup(TG_CHAT_DEBUG, item["debug_message_id"])
                    send_telegram("<b>[NEWS PUBLISHED AUTO]</b> <b>{}</b>\n\n{}".format(item.get("title", "Новина"), item.get("url", "")), chat_id=TG_CHAT_DEBUG)


def refresh_pending_debug_previews(state):
    if not TG_CHAT_DEBUG:
        return
    for state_key in ("news", "forum_news"):
        news_state = state.setdefault(state_key, {"last_seen_id": 0, "sent_ids": [], "pending": []})
        for item in news_state.get("pending", []):
            if item.get("status") not in {"pending", "approved"}:
                continue
            message_id = item.get("debug_message_id")
            if not message_id:
                continue
            if int(item.get("debug_preview_version", 0) or 0) >= NEWS_DEBUG_PREVIEW_VERSION:
                continue
            source_label = item.get("source") or ("forum" if state_key == "forum_news" else "telegram")
            preview = build_pending_preview(
                source_label,
                item.get("title", "Новина"),
                item.get("text", ""),
                item.get("url", ""),
            )
            if edit_telegram_message_text(TG_CHAT_DEBUG, message_id, preview, reply_markup={"inline_keyboard": []}):
                item["debug_preview_version"] = NEWS_DEBUG_PREVIEW_VERSION
                log("{} pending post {} debug preview refreshed".format(state_key, item.get("post_id")))


def execute_news_action(state, state_key, post_id, action, feedback_chat_id=None, feedback_message_id=None, callback_query_id=None):
    item = find_moderatable_news_item(state, state_key, post_id)
    if not item:
        if callback_query_id:
            answer_callback_query(callback_query_id, "Пост уже оброблений")
        elif feedback_chat_id:
            send_telegram("Пост уже оброблений", chat_id=str(feedback_chat_id))
        return True

    if action == "cancel":
        item["status"] = "cancelled"
        if feedback_chat_id and feedback_message_id:
            edit_telegram_reply_markup(feedback_chat_id, feedback_message_id)
        if callback_query_id:
            answer_callback_query(callback_query_id, "Скасовано")
        elif feedback_chat_id:
            send_telegram("Скасовано", chat_id=str(feedback_chat_id))
        return True

    if action == "publish":
        outgoing = build_news_post_message(item.get("title", "Новина Scryde x1000"), item.get("text", ""), item.get("url", ""))
        if send_telegram(outgoing, chat_id=TG_CHAT):
            item["status"] = "published"
            log("{} pending post {} published manually".format(state_key, post_id))
            if feedback_chat_id and feedback_message_id:
                edit_telegram_reply_markup(feedback_chat_id, feedback_message_id)
            if callback_query_id:
                answer_callback_query(callback_query_id, "Опубліковано")
            elif feedback_chat_id:
                send_telegram("Опубліковано", chat_id=str(feedback_chat_id))
        else:
            if callback_query_id:
                answer_callback_query(callback_query_id, "Не вдалося опублікувати")
            elif feedback_chat_id:
                send_telegram("Не вдалося опублікувати", chat_id=str(feedback_chat_id))
        return True

    if callback_query_id:
        answer_callback_query(callback_query_id, "Невідома дія")
    elif feedback_chat_id:
        send_telegram("Невідома дія", chat_id=str(feedback_chat_id))
    return True


def execute_news_delay(state, state_key, post_id, minutes, feedback_chat_id=None):
    item = find_moderatable_news_item(state, state_key, post_id)
    if not item:
        if feedback_chat_id:
            send_telegram("Pending post не знайдено", chat_id=str(feedback_chat_id))
        return True
    item["publish_after"] = int(time.time()) + max(1, int(minutes)) * 60
    if feedback_chat_id:
        send_telegram("Відкладено на {} хв: {} {}".format(minutes, state_key, post_id), chat_id=str(feedback_chat_id))
    return True


def execute_news_retry(state, state_key, post_id, feedback_chat_id=None):
    item = find_news_item(state, state_key, post_id, only_pending=False)
    if not item:
        if feedback_chat_id:
            send_telegram("Пост не знайдено", chat_id=str(feedback_chat_id))
        return True
    item["status"] = "pending"
    item["publish_after"] = int(time.time())
    item["created_at"] = int(time.time())
    if feedback_chat_id:
        send_telegram("Поставив у retry/pending: {} {}".format(state_key, post_id), chat_id=str(feedback_chat_id))
    return True


def send_news_list(state, chat_id):
    lines = ["<b>Pending news:</b>"]
    count = 0
    for state_key in ("news", "forum_news"):
        news_state = state.setdefault(state_key, {"last_seen_id": 0, "sent_ids": [], "pending": []})
        for item in news_state.get("pending", []):
            if item.get("status") not in {"pending", "approved"}:
                continue
            count += 1
            lines.append(format_news_item_summary(state_key, item))
            lines.append("/news_show {} {}".format(state_key, item.get("post_id")))
    if count == 0:
        lines.append("Нема pending новин.")
    lines.append("")
    lines.append(news_command_help())
    send_telegram("\n".join(lines), chat_id=str(chat_id))
    return True


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
    if action == "delay60":
        return execute_news_delay(
            state,
            state_key,
            post_id,
            60,
            feedback_chat_id=message.get("chat", {}).get("id"),
        )
    if action == "show":
        item = find_news_item(state, state_key, post_id, only_pending=False)
        chat_id = message.get("chat", {}).get("id")
        if item and chat_id:
            send_telegram(format_news_item_preview(state_key, item), chat_id=str(chat_id))
        elif chat_id:
            send_telegram("Пост не знайдено: {} {}".format(state_key, post_id), chat_id=str(chat_id))
        answer_callback_query(callback_id, "Показано")
        return True
    return execute_news_action(
        state,
        state_key,
        post_id,
        action,
        feedback_chat_id=message.get("chat", {}).get("id"),
        feedback_message_id=message.get("message_id"),
        callback_query_id=callback_id,
    )


def handle_news_command(state, message):
    text = (message.get("text") or "").strip()
    if not text.startswith("/news_"):
        return False

    parts = text.split()
    chat_id = str(message.get("chat", {}).get("id"))
    command = parts[0].split("@", 1)[0]

    if command == "/news_list":
        return send_news_list(state, chat_id)

    if command == "/news_help":
        send_telegram(news_command_help(), chat_id=chat_id)
        return True

    if len(parts) < 3:
        send_telegram(news_command_help(), chat_id=chat_id)
        return True

    state_key, post_id_raw = parts[1], parts[2]
    if state_key not in {"news", "forum_news"} or not post_id_raw.isdigit():
        send_telegram("Некоректна команда\n\n{}".format(news_command_help()), chat_id=chat_id)
        return True

    post_id = int(post_id_raw)

    if command == "/news_show":
        item = find_news_item(state, state_key, post_id, only_pending=False)
        if item:
            send_telegram(format_news_item_preview(state_key, item), chat_id=chat_id)
        else:
            send_telegram("Пост не знайдено: {} {}".format(state_key, post_id), chat_id=chat_id)
        return True

    if command == "/news_delay":
        if len(parts) != 4 or not parts[3].isdigit():
            send_telegram("Формат: /news_delay {} {} 60".format(state_key, post_id), chat_id=chat_id)
            return True
        return execute_news_delay(state, state_key, post_id, int(parts[3]), feedback_chat_id=chat_id)

    if command == "/news_retry":
        return execute_news_retry(state, state_key, post_id, feedback_chat_id=chat_id)

    action = "publish" if command == "/news_publish" else "cancel" if command == "/news_cancel" else None
    if not action:
        send_telegram(news_command_help(), chat_id=chat_id)
        return False

    return execute_news_action(
        state,
        state_key,
        post_id,
        action,
        feedback_chat_id=chat_id,
    )


def find_pending_by_debug_message_id(state, message_id):
    if not message_id:
        return None, None
    for state_key in ("news", "forum_news"):
        news_state = state.setdefault(state_key, {"last_seen_id": 0, "sent_ids": [], "pending": []})
        for item in news_state.get("pending", []):
            if item.get("status") not in {"pending", "approved"}:
                continue
            if int(item.get("debug_message_id", 0) or 0) == int(message_id):
                return state_key, item
    return None, None


def handle_news_reply_action(state, message):
    text = (message.get("text") or "").strip().lower()
    if not text:
        return False
    chat_id = str(message.get("chat", {}).get("id"))
    if TG_CHAT_DEBUG and chat_id != str(TG_CHAT_DEBUG):
        return False
    reply_to = message.get("reply_to_message") or {}
    replied_message_id = reply_to.get("message_id")
    state_key, item = find_pending_by_debug_message_id(state, replied_message_id)
    if not item:
        return False

    post_id = int(item.get("post_id"))
    if text in {"+", "publish", "post", "публікуй", "опублікуй"}:
        return execute_news_action(state, state_key, post_id, "publish", feedback_chat_id=chat_id)
    if text in {"-", "cancel", "skip", "скасувати", "відміна"}:
        return execute_news_action(state, state_key, post_id, "cancel", feedback_chat_id=chat_id)
    if text in {"show", "покажи"}:
        send_telegram(format_news_item_preview(state_key, item), chat_id=chat_id)
        return True
    m = re.match(r"^(?:delay|відкласти)\s+(\d{1,4})$", text)
    if m:
        return execute_news_delay(state, state_key, post_id, int(m.group(1)), feedback_chat_id=chat_id)
    send_telegram("Не зрозумів дію. Відповідай на pending-пост: +, -, delay 60 або show", chat_id=chat_id)
    return True


def acknowledge_telegram_updates(url, next_offset):
    try:
        response = requests.get(
            url,
            params={
                "offset": next_offset,
                "limit": 1,
                "timeout": 0,
                "allowed_updates": json.dumps(["callback_query", "message"]),
            },
            timeout=20,
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        log("getUpdates acknowledgement failed: {}".format(exc))
        return False


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
                "allowed_updates": json.dumps(["callback_query", "message"]),
            },
            timeout=20,
        )
        response.raise_for_status()
        updates = response.json().get("result", [])
    except Exception as exc:
        log("getUpdates callback fetch failed: {}".format(exc))
        return False

    if not updates:
        return False

    max_update_id = max(int(update.get("update_id", 0) or 0) for update in updates)
    next_offset = max_update_id + 1
    if not acknowledge_telegram_updates(url, next_offset):
        log("Telegram updates not processed because acknowledgement failed")
        return False
    meta["tg_update_offset"] = next_offset

    handled_any = False
    for update in updates:
        callback = update.get("callback_query")
        if callback:
            handled_any = handle_news_callback(state, callback) or handled_any
        message = update.get("message")
        if message:
            if handle_news_reply_action(state, message):
                handled_any = True
            elif handle_news_command(state, message):
                handled_any = True

    return handled_any

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


def classify_page_text(text):
    lower = (text or "").lower()
    markers = {
        "captcha": ["captcha", "g-recaptcha", "hcaptcha"],
        "cloudflare": ["cloudflare", "checking your browser", "cf-chl", "challenge-platform"],
        "access_denied": ["access denied", "403 forbidden", "forbidden"],
        "empty_page": [],
    }
    if not lower.strip():
        return "empty_page"
    for reason, needles in markers.items():
        if needles and any(needle in lower for needle in needles):
            return reason
    return "next_data_missing"


def ensure_diag_dir():
    try:
        os.makedirs(SIEGE_DIAG_DIR, exist_ok=True)
        return True
    except Exception as exc:
        log("diagnostics directory failed: {}".format(exc))
        return False


def write_diagnostic(page_key, reason, payload):
    if not ensure_diag_dir():
        return
    safe_reason = re.sub(r"[^a-zA-Z0-9_.-]+", "_", reason or "unknown")[:60]
    path = os.path.join(SIEGE_DIAG_DIR, "{}_{}_{}.json".format(int(time.time()), page_key, safe_reason))
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        log("{} diagnostic written {}".format(page_key, path))
    except Exception as exc:
        log("{} diagnostic write failed: {}".format(page_key, exc))


def send_fetch_debug(page_key, reason, url, detail=None, title=None, final_url=None, snippet=None):
    detail = compact_text(str(detail or ""), 260)
    snippet = compact_text(snippet or "", 360)
    lines = [
        "<b>Scryde fetch/parser issue</b>",
        "page: <code>{}</code>".format(escape_debug(page_key)),
        "reason: <code>{}</code>".format(escape_debug(reason)),
        "url: {}".format(escape_debug(final_url or url)),
    ]
    if title:
        lines.append("title: <code>{}</code>".format(escape_debug(compact_text(title, 120))))
    if detail:
        lines.append("detail: <code>{}</code>".format(escape_debug(detail)))
    if snippet and DEBUG_SCRYDE_FETCH:
        lines.append("snippet: <code>{}</code>".format(escape_debug(snippet)))
    send_debug("\n".join(lines))


def extract_next_data_text(page, page_key, attempt):
    try:
        text = page.locator("script#__NEXT_DATA__").text_content(timeout=1500)
        if text:
            log("{} NEXT_DATA extracted via js on attempt {}".format(page_key, attempt))
            return text
    except PlaywrightTimeoutError:
        return None
    except PlaywrightError as exc:
        log("{} NEXT_DATA js extraction failed on attempt {}: {}".format(page_key, attempt, compact_text(str(exc), 160)))
    return None


def collect_page_snapshot(page, html_text, page_key, reason, url):
    title = ""
    final_url = url
    body_text = ""
    try:
        title = page.title(timeout=2000)
    except Exception:
        pass
    try:
        final_url = page.url or url
    except Exception:
        pass
    try:
        body_text = page.locator("body").inner_text(timeout=1500)
    except Exception:
        body_text = html_text or ""
    snippet = compact_text(body_text or html_text or "", 700)
    payload = {
        "page": page_key,
        "reason": reason,
        "url": url,
        "final_url": final_url,
        "title": title,
        "snippet": snippet,
        "html_length": len(html_text or ""),
        "timestamp": int(time.time()),
    }
    write_diagnostic(page_key, reason, payload)
    return payload


def fetch_page_payload(pw, url, page_key, attempt, goto_timeout=45000, selector_timeout=15000):
    result = {"html": "", "next_data": None, "snapshot": None, "reason": None}
    browser = pw.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        locale="uk-UA",
        timezone_id="Europe/Kyiv",
        viewport={"width": 1366, "height": 768},
        extra_http_headers={"Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7"},
    )
    page = context.new_page()
    page.route(
        "**/*",
        lambda route: route.abort()
        if route.request.resource_type in {"image", "font", "media", "stylesheet"}
        else route.continue_(),
    )
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=goto_timeout)
        try:
            page.wait_for_selector("script#__NEXT_DATA__", timeout=selector_timeout)
        except PlaywrightTimeoutError:
            page.wait_for_timeout(2000)
        result["next_data"] = extract_next_data_text(page, page_key, attempt)
        html = read_page_content(page, page_key, attempt) if not result["next_data"] else ""
        result["html"] = html
        if not result["next_data"]:
            result["reason"] = classify_page_text(html)
            result["snapshot"] = collect_page_snapshot(page, html, page_key, result["reason"], url)
        log("{} fetch attempt {} completed".format(page_key, attempt))
    finally:
        browser.close()
    return result


def read_page_content(page, page_key, attempt):
    for content_attempt in range(1, 4):
        try:
            if content_attempt > 1:
                page.wait_for_load_state("domcontentloaded", timeout=3000)
                page.wait_for_timeout(500)
            return page.content()
        except PlaywrightError as exc:
            message = str(exc)
            if "page is navigating and changing the content" not in message:
                raise
            if content_attempt == 3:
                log("{} content read still racing navigation on attempt {}; treating as no data".format(page_key, attempt))
                return ""
            log("{} content read raced navigation on attempt {}.{}".format(page_key, attempt, content_attempt))
    return ""


def find_next_data_script(html):
    soup = BeautifulSoup(html, "html.parser")
    return soup.find("script", id="__NEXT_DATA__")


def find_items_candidate(value):
    if isinstance(value, dict):
        if isinstance(value.get("items"), list):
            items = value["items"]
            if items and all(isinstance(item, dict) for item in items):
                sample = items[:5]
                score = 0
                for item in sample:
                    keys = set(item.keys())
                    if keys.intersection({"id", "name", "owner", "siege_sides", "image"}):
                        score += 1
                if score:
                    return items
        if isinstance(value.get("rankingRows"), dict):
            rows = value["rankingRows"].get("items")
            if isinstance(rows, list):
                return rows
        for child in value.values():
            result = find_items_candidate(child)
            if result is not None:
                return result
    elif isinstance(value, list):
        if value and all(isinstance(item, dict) for item in value):
            score = 0
            sample = value[:5]
            for item in sample:
                keys = set(item.keys())
                if keys.intersection({"id", "name", "owner", "siege_sides", "image"}):
                    score += 1
            if score:
                return value
        for child in value:
            result = find_items_candidate(child)
            if result is not None:
                return result
    return None


def extract_ranking_items(data, page_key):
    try:
        items = data["props"]["pageProps"]["rankingRows"]["items"]
        if isinstance(items, list):
            return items, "primary"
        raise TypeError("rankingRows.items is {}".format(type(items).__name__))
    except (KeyError, TypeError) as exc:
        items = find_items_candidate(data)
        if items is not None:
            log("{} ranking items found via fallback after schema miss: {}".format(page_key, exc))
            notify_schema_fallback(page_key, data, exc)
            return items, "fallback"
        top_keys = sorted(data.keys()) if isinstance(data, dict) else []
        raise ValueError("schema_changed: rankingRows.items missing; top_keys={}".format(top_keys)) from exc


def record_fetch_failure(state, page_key, url, reason, detail=None, snapshot=None):
    _error_counts[page_key] += 1
    log("{} fetch/parser failed: {} {}".format(page_key, reason, compact_text(str(detail or ""), 180)))
    should_notify = DEBUG_SCRYDE_FETCH or _error_counts[page_key] == SITE_ERROR_NOTIFY_AFTER
    if snapshot and should_notify:
        send_fetch_debug(
            page_key,
            reason,
            url,
            detail=detail,
            title=snapshot.get("title"),
            final_url=snapshot.get("final_url"),
            snippet=snapshot.get("snippet"),
        )
    elif should_notify:
        send_debug(DEBUG_SITE_DOWN.format(page=page_key, count=_error_counts[page_key], url=url))


def reset_fetch_failure(page_key):
    clear_needed = _error_counts[page_key] >= SITE_ERROR_NOTIFY_AFTER
    if clear_needed:
        send_debug(DEBUG_SITE_UP.format(page=page_key))
    _error_counts[page_key] = 0
    _challenge_counts[page_key] = 0


def notify_schema_fallback(page_key, data, detail):
    top_keys = sorted(data.keys()) if isinstance(data, dict) else []
    payload = {
        "page": page_key,
        "reason": "schema_fallback",
        "detail": str(detail),
        "top_keys": top_keys,
        "timestamp": int(time.time()),
    }
    write_diagnostic(page_key, "schema_fallback", payload)
    if not DEBUG_SCRYDE_FETCH:
        return
    send_fetch_debug(
        page_key,
        "schema_fallback",
        FORTRESS_URL if page_key == "fortresses" else CASTLE_URL,
        detail="rankingRows.items missing, fallback parser succeeded; top_keys={}".format(top_keys),
    )


def fetch_page_data(url, page_key, state):
    if should_backoff(state, page_key):
        return None

    random_prewait(page_key)

    retry_count = FORTRESS_ANTIBOT_RETRIES if page_key == "fortresses" else CASTLE_ANTIBOT_RETRIES
    next_data_text = None
    last_snapshot = None
    last_reason = "next_data_missing"
    with sync_playwright() as pw:
        for attempt in range(1, retry_count + 2):
            if attempt > 1:
                log("{} retrying after anti-bot/no data".format(page_key))
            payload = fetch_page_payload(
                pw,
                url,
                page_key,
                attempt,
                goto_timeout=45000 if attempt == 1 else 25000,
                selector_timeout=15000 if attempt == 1 else 8000,
            )
            next_data_text = payload.get("next_data")
            if not next_data_text:
                script_tag = find_next_data_script(payload.get("html") or "")
                if script_tag and script_tag.string:
                    next_data_text = script_tag.string
            last_snapshot = payload.get("snapshot") or last_snapshot
            last_reason = payload.get("reason") or last_reason
            if next_data_text:
                break
    if not next_data_text:
        _challenge_counts[page_key] += 1
        log("{} anti-bot/no data, count={}".format(page_key, _challenge_counts[page_key]))
        if _challenge_counts[page_key] >= 1:
            set_backoff(state, page_key, BACKOFF_MINUTES_ON_CHALLENGE)
        record_fetch_failure(state, page_key, url, last_reason, detail="__NEXT_DATA__ missing", snapshot=last_snapshot)
        return None

    clear_backoff(state, page_key)

    data = json.loads(next_data_text)
    items, source = extract_ranking_items(data, page_key)
    reset_fetch_failure(page_key)
    log("{} loaded {} objects ({})".format(page_key, len(items), source))
    return items


def safe_fetch_page_data(url, page_key, state):
    try:
        items = fetch_page_data(url, page_key, state)
        if items is None:
            log("{} skipped, preserving previous state".format(page_key))
        return items
    except json.JSONDecodeError as exc:
        record_fetch_failure(state, page_key, url, "invalid_next_data_json", detail=exc)
    except PlaywrightTimeoutError as exc:
        record_fetch_failure(state, page_key, url, "playwright_timeout", detail=exc)
    except PlaywrightError as exc:
        record_fetch_failure(state, page_key, url, "playwright_error", detail=exc)
    except ValueError as exc:
        record_fetch_failure(state, page_key, url, "schema_changed", detail=exc)
    except Exception as exc:
        record_fetch_failure(state, page_key, url, type(exc).__name__, detail=exc)
    log("{} skipped after fetch/parser failure, preserving previous state".format(page_key))
    return None


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


def default_object_state():
    return {
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
    }


def copy_object_state(dst, src):
    for key in default_object_state().keys():
        dst[key] = src.get(key, default_object_state()[key])


def process_defence(state_section, items, obj_key, page_url):
    o = OBJ[obj_key]
    obj_type = o["acc"]
    root_state = state_section.get("_root_state", {})
    tracked = state_section.setdefault("objects", {})

    if state_section.get("id") and str(state_section.get("id")) not in tracked:
        tracked[str(state_section["id"])] = {
            key: state_section.get(key, default_object_state()[key])
            for key in default_object_state().keys()
        }

    our_items = []
    for item in items:
        owner = item.get("owner")
        if owner and owner.get("name") == OUR_CLAN:
            our_items.append(item)

    current_ids = set()
    processed = []
    for our in our_items:
        fort_name = our["name"]
        fort_id = our["id"]
        fort_key = str(fort_id)
        current_ids.add(fort_key)
        s = tracked.setdefault(fort_key, default_object_state())
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
            if should_notify and not should_send_siege_alert(root_state, alert_key, now):
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
                    remember_siege_alert(root_state, alert_key, now)

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
        processed.append((our, s, bool(attackers and siege_at)))

    for fort_key, s in list(tracked.items()):
        if fort_key in current_ids:
            continue
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

    if processed:
        preferred = next((entry for entry in processed if entry[2]), processed[0])
        copy_object_state(state_section, preferred[1])
    else:
        active = [obj_state for obj_state in tracked.values() if obj_state.get("had")]
        if active:
            copy_object_state(state_section, active[0])
        else:
            state_section["had"] = False
    return state_section


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
    if RUN_NEWS:
        process_channel_news(state)
        process_forum_news(state)
        refresh_pending_debug_previews(state)
        process_pending_news_queue(state)

    if RUN_SIEGES:
        fortress_items = safe_fetch_page_data(FORTRESS_URL, "fortresses", state)
        delay = random.randint(*BETWEEN_REQUESTS_DELAY)
        log("between requests delay {}s".format(delay))
        time.sleep(delay)
        castle_items = safe_fetch_page_data(CASTLE_URL, "castles", state)

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
