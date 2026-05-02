#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Scryde Fortress & Castle Bot для клану BSOE
Моніторить фортеці і замки: атаки на нас, наші атаки, втрата об'єктів
"""

import requests
from bs4 import BeautifulSoup
import json
import os
import subprocess
import time
import random
import threading
import logging
import platform
from logging.handlers import RotatingFileHandler
from datetime import datetime
from urllib.parse import urlparse

# ─── Налаштування (з config.py) ──────────────────────────────────────────────
try:
    from config import (
        TG_TOKEN, TG_CHAT, TG_CHAT_DEBUG,
        OUR_CLAN,
        FORTRESS_URL, CASTLE_URL,
        STATE_FILE,
        CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX,
        BETWEEN_REQUESTS_DELAY,
        SITE_ERROR_NOTIFY_AFTER,
    )
except ImportError:
    raise SystemExit("ПОМИЛКА: файл config.py не знайдено поруч з fortress_bot.py")

try:
    from messages import (
        OBJ,
        SIEGE_ATTACK, SIEGE_ATTACK_CARD_TITLE,
        SIEGE_REMINDER, SIEGE_REMINDER_CARD_TITLE,
        SIEGE_CANCELLED, OBJECT_LOST,
        WE_ATTACK, WE_CANCELLED,
        STATUS_SIEGE, STATUS_PEACE,
        STATUS_NO_OBJECT, STATUS_CARD_TITLE_SIEGE, STATUS_CARD_TITLE_PEACE,
        HELP_TEXT,
        DEBUG_BOT_STARTED, DEBUG_BOT_STOPPED,
        DEBUG_SITE_DOWN, DEBUG_SITE_UP,
        DEBUG_CYCLE_ERROR, DEBUG_CRITICAL,
    )
except ImportError:
    raise SystemExit("ПОМИЛКА: файл messages.py не знайдено поруч з fortress_bot.py")

# ─── Логування ───────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)
fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

fh = RotatingFileHandler(
    "/root/scryde_fortress_bot/fortress_bot.log",
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding="utf-8",
)
fh.setFormatter(fmt)
log.addHandler(fh)

sh = logging.StreamHandler()
sh.setFormatter(fmt)
log.addHandler(sh)

# Лічильники помилок — окремо для кожного сайту
_error_counts = {"fortresses": 0, "castles": 0}

try:
    from card_builder import build_card, C_RED, C_GOLD
    CARDS_ENABLED = True
except ImportError:
    CARDS_ENABLED = False

# ─── User-Agents ─────────────────────────────────────────────────────────────
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": random.choice([
            "uk-UA,uk;q=0.9,en;q=0.8",
            "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
            "en-US,en;q=0.9,uk;q=0.8",
            "ru-RU,ru;q=0.9,uk;q=0.8,en;q=0.7",
        ]),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": random.choice(["max-age=0", "no-cache"]),
    }

# ─── Telegram ────────────────────────────────────────────────────────────────
def send_telegram(text, retries=3, chat_id=None):
    """Відправляє повідомлення в TG. До 3 спроб з паузою між ними."""
    url = "https://api.telegram.org/bot{}/sendMessage".format(TG_TOKEN)
    payload = {
        "chat_id": chat_id or TG_CHAT,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=10)
            r.raise_for_status()
            log.info("TG відправлено: {}...".format(text[:80].strip()))
            return True
        except requests.exceptions.ConnectionError as e:
            log.error("TG спроба {}/{}: немає з'єднання: {}".format(attempt, retries, e))
        except requests.exceptions.Timeout:
            log.error("TG спроба {}/{}: таймаут".format(attempt, retries))
        except requests.exceptions.HTTPError as e:
            log.error("TG спроба {}/{}: HTTP {}: {}".format(
                attempt, retries, e.response.status_code, e.response.text))
            if e.response.status_code < 500:
                return False
        except Exception as e:
            log.error("TG спроба {}/{}: невідома помилка: {}".format(attempt, retries, e))
        if attempt < retries:
            time.sleep(5 * attempt)
    log.error("TG: всі {} спроби невдалі".format(retries))
    return False

def send_debug(text):
    """Відправляє технічне повідомлення в дебаг чат."""
    if TG_CHAT_DEBUG and TG_CHAT_DEBUG != "YOUR_DEBUG_CHAT_ID_HERE":
        return send_telegram(text, chat_id=TG_CHAT_DEBUG)
    else:
        log.info("DEBUG (чат не налаштовано): {}".format(text[:80]))
        return False

# ─── Парсер ──────────────────────────────────────────────────────────────────
def send_telegram_photo(image_bytes, caption, chat_id=None):
    """Відправляє фото з підписом в TG. До 3 спроб."""
    url = "https://api.telegram.org/bot{}/sendPhoto".format(TG_TOKEN)
    for attempt in range(1, 4):
        try:
            r = requests.post(
                url,
                data={"chat_id": chat_id or TG_CHAT, "caption": caption,
                      "parse_mode": "HTML", "disable_web_page_preview": True},
                files={"photo": ("card_{}.png".format(int(time.time())), image_bytes, "image/png")},
                timeout=20,
            )
            r.raise_for_status()
            log.info("TG фото відправлено")
            return True
        except requests.exceptions.ConnectionError as e:
            log.error("TG photo спроба {}/{}: немає з'єднання: {}".format(attempt, 3, e))
        except requests.exceptions.Timeout:
            log.error("TG photo спроба {}/{}: таймаут".format(attempt, 3))
        except requests.exceptions.HTTPError as e:
            log.error("TG photo спроба {}/{}: HTTP {}: {}".format(
                attempt, 3, e.response.status_code, e.response.text))
            if e.response.status_code < 500:
                return False
        except Exception as e:
            log.error("TG photo спроба {}/{}: {}".format(attempt, 3, e))
        if attempt < 3:
            time.sleep(5 * attempt)
    log.error("TG photo: всі спроби невдалі — fallback на текст")
    return False

def send_notification(text, image_bytes=None, chat_id=None):
    """
    Відправляє повідомлення: з фото якщо є image_bytes, інакше текст.
    При невдачі фото — fallback на текстове.
    """
    if image_bytes:
        # caption для фото — скорочений текст без HTML тегів форматування посилань
        if send_telegram_photo(image_bytes, text, chat_id=chat_id):
            return True
        log.warning("Фото не відправилось — відправляємо текст")
    return send_telegram(text, chat_id=chat_id)

# Глобальна сесія — зберігає cookies між запитами
_session = requests.Session()
_session_warmed = False

def _is_antibot_response(response):
    """Перевіряє чи відповідь схожа на anti-bot челендж замість даних сторінки."""
    if response is None:
        return True

    status = response.status_code
    headers = response.headers or {}
    text = response.text or ""

    location = headers.get("Location", "")
    server = (headers.get("Server") or "").lower()
    set_cookie = (headers.get("Set-Cookie") or "").lower()
    text_l = text.lower()

    if status in (301, 302, 303, 307, 308) and location:
        if location == response.url or location.endswith(urlparse(response.url).path):
            return True

    anti_markers = (
        "variti",
        "ipp_uid",
        "ipp_key",
        "ipp_sign",
        "fingerprintjs",
        "cookieencrypt",
    )

    marker_hit = any(m in text_l for m in anti_markers) or any(m in set_cookie for m in anti_markers) or "variti" in server
    no_data = "__NEXT_DATA__" not in text
    return marker_hit and no_data

def _apply_solver_cookies(cookie_map, url):
    """Записує cookies, отримані браузером, в requests-сесію."""
    host = urlparse(url).hostname or ""
    for name, value in cookie_map.items():
        _session.cookies.set(name, value, domain=".scryde.game", path="/")
        if host:
            _session.cookies.set(name, value, domain=host, path="/")

def _solve_antibot_with_playwright(url):
    """Одноразово проходить JS-челендж у headless Chromium і повертає cookies."""
    def _solver_fallback():
        cookie_map = _solve_antibot_with_docker(url)
        if cookie_map:
            return cookie_map
        return None

    libc_name, libc_ver = platform.libc_ver()
    if libc_name == "glibc":
        try:
            major, minor = [int(x) for x in libc_ver.split(".")[:2]]
        except Exception:
            major, minor = (0, 0)
        if (major, minor) < (2, 27):
            log.warning("[anti-bot] GLIBC {} занадто старий для локального Playwright, йдемо в Docker fallback".format(libc_ver or "unknown"))
            return _solver_fallback()

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except Exception as e:
        log.error("[anti-bot] Playwright недоступний: {}".format(e))
        return _solver_fallback()

    log.warning("[anti-bot] Виявлено челендж. Запускаю Playwright solver...")

    html = ""
    cookies = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            context = browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                locale="uk-UA",
                viewport={"width": 1366, "height": 768},
            )
            page = context.new_page()
            page.set_default_navigation_timeout(45000)

            def _route_handler(route, request):
                if request.resource_type in {"image", "media", "font", "stylesheet"}:
                    route.abort()
                else:
                    route.continue_()

            page.route("**/*", _route_handler)
            page.goto(url, wait_until="domcontentloaded")

            try:
                page.wait_for_selector("script#__NEXT_DATA__", timeout=20000)
            except PlaywrightTimeoutError:
                page.wait_for_timeout(4000)

            html = page.content()
            cookies = context.cookies()
            browser.close()
    except Exception as e:
        log.error("[anti-bot] Playwright solver впав: {}".format(e))
        return _solver_fallback()

    if "__NEXT_DATA__" not in html:
        log.error("[anti-bot] Playwright відкрив сторінку, але дані все ще недоступні")
        return None

    cookie_map = {}
    for c in cookies:
        domain = c.get("domain", "")
        if "scryde.game" in domain:
            cookie_map[c["name"]] = c["value"]

    if not cookie_map:
        log.error("[anti-bot] Playwright не повернув cookies для scryde.game")
        return None

    log.info("[anti-bot] Playwright solver успішний, cookies: {}".format(", ".join(sorted(cookie_map.keys()))))
    return cookie_map

def _solve_antibot_with_docker(url):
    """Fallback для CentOS 7: запускає Playwright всередині Docker-контейнера."""
    image = "scryde-playwright-solver:1.58.0"
    project_dir = os.path.dirname(os.path.abspath(__file__))

    cmd = [
        "docker", "run", "--rm",
        "-e", "TARGET_URL={}".format(url),
        "-v", "{}:/work".format(project_dir),
        "-w", "/work",
        image,
        "node", "docker_solver.js",
    ]

    log.warning("[anti-bot] Пробую Docker fallback solver...")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except Exception as e:
        log.error("[anti-bot] Docker fallback не стартував: {}".format(e))
        return None

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        if stderr:
            log.error("[anti-bot] Docker fallback помилка: {}".format(stderr[:400]))
            if "Unable to find image" in stderr:
                log.error("[anti-bot] Потрібно один раз зібрати image: docker build -t scryde-playwright-solver:1.58.0 -f Dockerfile.solver .")
        else:
            log.error("[anti-bot] Docker fallback завершився з кодом {}".format(proc.returncode))
        return None

    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    if not lines:
        log.error("[anti-bot] Docker fallback не повернув output")
        return None

    payload = lines[-1]
    try:
        cookie_map = json.loads(payload)
    except Exception:
        log.error("[anti-bot] Docker fallback повернув не JSON: {}".format(payload[:200]))
        return None

    if not isinstance(cookie_map, dict) or not cookie_map:
        log.error("[anti-bot] Docker fallback повернув порожні cookies")
        return None

    log.info("[anti-bot] Docker fallback успішний, cookies: {}".format(", ".join(sorted(cookie_map.keys()))))
    return cookie_map

def _warm_up_session():
    """Відвідуємо головну сторінку щоб отримати cookies і не виглядати як бот."""
    global _session_warmed
    try:
        r = _session.get(
            "https://ua.scryde.game/",
            headers=get_headers(),
            timeout=15,
        )
        if _is_antibot_response(r):
            log.warning("Warm-up отримав anti-bot відповідь")
            _session_warmed = False
        else:
            _session_warmed = True
            log.info("Сесія прогріта (cookies отримано)")
    except Exception as e:
        log.warning("Warm-up не вдався: {}".format(e))

def fetch_page_data(url, page_key):
    """
    Завантажує сторінку і витягує items з __NEXT_DATA__.
    page_key: 'fortresses' або 'castles' — для лічильника помилок.
    3 спроби з паузою. Сповіщає в дебаг після SITE_ERROR_NOTIFY_AFTER помилок підряд.
    """
    global _error_counts, _session_warmed

    # Прогріваємо сесію при першому запиті
    if not _session_warmed:
        _warm_up_session()
        time.sleep(random.uniform(2.0, 5.0))

    last_error = None
    for attempt in range(1, 4):
        try:
            r = _session.get(url, headers=get_headers(), timeout=20)
            r.raise_for_status()

            if _is_antibot_response(r):
                log.warning("[{}] Отримано anti-bot challenge".format(page_key))
                cookie_map = _solve_antibot_with_playwright(url)
                if cookie_map:
                    _apply_solver_cookies(cookie_map, url)
                    _session_warmed = True
                    time.sleep(random.uniform(1.0, 2.5))
                    r = _session.get(url, headers=get_headers(), timeout=25)
                    r.raise_for_status()
                    if _is_antibot_response(r):
                        last_error = "Anti-bot challenge не пройдено навіть після solver"
                        if attempt < 3:
                            pause = attempt * 20
                            log.warning("[{}] Пауза {}с перед повторною спробою...".format(page_key, pause))
                            time.sleep(pause)
                        continue
                else:
                    last_error = "Anti-bot challenge, solver не спрацював"
                    if attempt < 3:
                        pause = attempt * 20
                        log.warning("[{}] Пауза {}с перед повторною спробою...".format(page_key, pause))
                        time.sleep(pause)
                    continue

            # Перевіряємо чи не капча
            if len(r.text) < 50000 and '__NEXT_DATA__' not in r.text:
                log.warning("[{}] Схоже на капчу (розмір: {}б) — скидаємо сесію".format(
                    page_key, len(r.text)))
                _session.cookies.clear()
                _session_warmed = False
                last_error = "Капча або редирект (розмір {}б)".format(len(r.text))
                if attempt < 3:
                    pause = attempt * 20
                    log.warning("[{}] Пауза {}с перед повторною спробою...".format(page_key, pause))
                    time.sleep(pause)
                    _warm_up_session()
                    time.sleep(random.uniform(3.0, 7.0))
                continue

            last_error = None
            break
        except requests.exceptions.ConnectionError as e:
            last_error = "Сайт недоступний: {}".format(e)
        except requests.exceptions.Timeout:
            last_error = "Таймаут при завантаженні"
        except requests.exceptions.HTTPError as e:
            last_error = "HTTP помилка: {}".format(e)
            if e.response.status_code < 500:
                break
        except Exception as e:
            last_error = "Помилка: {}".format(e)

        if attempt < 3:
            pause = attempt * 15
            log.warning("[{}] Спроба {}/3: {}. Пауза {}с...".format(page_key, attempt, last_error, pause))
            time.sleep(pause)

    if last_error:
        log.error("[{}] Всі спроби невдалі: {}".format(page_key, last_error))
        _error_counts[page_key] += 1
        log.warning("[{}] Помилок підряд: {}".format(page_key, _error_counts[page_key]))
        if _error_counts[page_key] == SITE_ERROR_NOTIFY_AFTER:
            send_debug(DEBUG_SITE_DOWN.format(
                page=page_key, count=_error_counts[page_key], url=url,
            ))
        return None

    if _error_counts[page_key] > 0:
        log.info("[{}] Сайт знову доступний після {} помилок.".format(page_key, _error_counts[page_key]))
        if _error_counts[page_key] >= SITE_ERROR_NOTIFY_AFTER:
            send_debug(DEBUG_SITE_UP.format(page=page_key))
        _error_counts[page_key] = 0

    try:
        soup = BeautifulSoup(r.text, "html.parser")
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if not script_tag:
            log.error("[{}] __NEXT_DATA__ не знайдено!".format(page_key))
            return None
        data = json.loads(script_tag.string)
        items = data["props"]["pageProps"]["rankingRows"]["items"]
        log.info("[{}] Завантажено {} об'єктів".format(page_key, len(items)))
        return items
    except json.JSONDecodeError as e:
        log.error("[{}] Помилка парсингу JSON: {}".format(page_key, e))
    except KeyError as e:
        log.error("[{}] Змінилась структура JSON, ключ не знайдено: {}".format(page_key, e))
    except Exception as e:
        log.error("[{}] Несподівана помилка парсингу: {}".format(page_key, e))
    return None

# ─── Хелпери ─────────────────────────────────────────────────────────────────
def get_attackers(item):
    """Повертає список імен атакуючих кланів."""
    siege_sides = item.get("siege_sides", [])
    if not siege_sides or isinstance(siege_sides, list):
        return []
    return [a["name"] for a in siege_sides.get("attackers", []) if "name" in a]

def format_time(ts):
    """Unix timestamp → читабельний час."""
    if not ts:
        return "невідомо"
    try:
        return datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
    except Exception:
        return str(ts)

# ─── Стан ────────────────────────────────────────────────────────────────────
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("Не вдалося прочитати state.json: {}. Починаємо з нуля.".format(e))
    return _empty_state()

def _empty_state():
    return {
        # --- Наша фортеця (ми власник) ---
        "fortress": {
            "had":               False,
            "name":              None,
            "id":                None,
            "last_attackers":    [],
            "owner_image":       None,
            "last_siege_at":     0,
            "notified_siege":    False,
            "notified_lost":     False,
            "siege_first_notify": 0,
            "notified_reminder": False,
        },
        # --- Наш замок (ми власник) ---
        "castle": {
            "had":               False,
            "name":              None,
            "id":                None,
            "last_attackers":    [],
            "owner_image":       None,
            "last_siege_at":     0,
            "notified_siege":    False,
            "notified_lost":     False,
            "siege_first_notify": 0,
            "notified_reminder": False,
        },
        # --- Ми атакуємо чужі фортеці ---
        "our_fortress_attacks": {},   # {fort_id: {name, siege_at, notified}}
        # --- Ми атакуємо чужі замки ---
        "our_castle_attacks":   {},   # {castle_id: {name, siege_at, notified}}
    }

def save_state(state):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.error("Помилка збереження стану: {}".format(e))

# ─── Логіка: захист об'єкта ──────────────────────────────────────────────────
def process_defence(state_section, items, obj_key, page_url):
    """
    Перевіряє об'єкт де ми власник (фортеця або замок).
    obj_key: 'fortress' або 'castle' — ключ з OBJ dict.
    Повертає змінений state_section.
    """
    o = OBJ[obj_key]  # всі форми: o["nom"], o["acc"], o["our_acc"] і тд
    obj_type = o["acc"]  # для зворотної сумісності де ще використовується
    s = state_section
    our = None
    for item in items:
        owner = item.get("owner")
        if owner and owner.get("name") == OUR_CLAN:
            our = item
            break

    if our:
        fort_name = our["name"]
        fort_id   = our["id"]
        attackers = get_attackers(our)
        siege_at  = our.get("siege_at", 0)

        if not s["had"]:
            log.info("Виявлено наш {}: {}. Слідкуємо.".format(obj_type, fort_name))
            s["had"]             = True
            s["name"]            = fort_name
            s["id"]              = fort_id
            s["notified_lost"]   = False
            s["notified_siege"]  = False
            s["last_attackers"]  = []
            s["last_siege_at"]   = 0

        s["name"]        = fort_name
        s["id"]          = fort_id
        s["owner_image"] = (our.get("owner") or {}).get("image")
        s["notified_lost"] = False  # скидаємо щоразу поки ми власник

        if attackers and siege_at:
            now            = int(time.time())
            attackers_str  = ", ".join(attackers)
            siege_time_str = format_time(siege_at)
            # Порівнюємо тільки імена (image URL може змінитись)
            cur_names  = sorted(a if isinstance(a, str) else a.get("name","") for a in attackers)
            prev_names = sorted(a if isinstance(a, str) else a.get("name","") for a in s.get("last_attackers", []))
            new_attackers  = cur_names != prev_names
            new_siege_time = siege_at != s.get("last_siege_at", 0)
            mins_left      = (siege_at - now) // 60

            if not s["notified_siege"] or new_attackers or new_siege_time:
                msg = SIEGE_ATTACK.format(
                    our_acc=o["our_acc"], nom=o["nom"],
                    name=fort_name, attackers=attackers_str,
                    time=siege_time_str, url=page_url,
                )
                image = None
                if CARDS_ENABLED:
                    try:
                        image = build_card(
                            obj_type     = obj_type,
                            obj_name     = fort_name,
                            event_text   = SIEGE_ATTACK_CARD_TITLE.format(our_acc=o["our_acc"]),
                            event_color  = C_RED,
                            owner_name   = OUR_CLAN,
                            owner_icon_url = (our.get("owner") or {}).get("image"),
                            attackers    = (our.get("siege_sides") or {}).get("attackers", []),
                            siege_time   = siege_time_str,
                            page_url     = page_url,
                        )
                        log.debug("build_card siege: {}".format("OK" if image else "None"))
                    except Exception as e:
                        log.error("build_card siege FAILED: {}".format(e))
                        import traceback; log.error(traceback.format_exc())
                if send_notification(msg, image):
                    if not s["notified_siege"]:
                        s["siege_first_notify"] = now
                        s["notified_reminder"]  = False
                    s["notified_siege"] = True
                    # Зберігаємо повні dict {name, image} для картки
                    siege_sides = our.get("siege_sides") or {}
                    atk_list = siege_sides.get("attackers", []) if isinstance(siege_sides, dict) else []
                    s["last_attackers"] = [
                        {"name": a.get("name","?"), "image": a.get("image")}
                        for a in atk_list
                    ]
                    s["last_siege_at"]  = siege_at
                else:
                    log.warning("TG не відправлено — спробуємо наступного циклу")

            # Нагадування за 25 хв — тільки якщо з першого сповіщення пройшло >1.5 год
            first_notify     = s.get("siege_first_notify", 0)
            time_since_first = now - first_notify if first_notify else 0
            log.info("Нагадування: mins_left={}, time_since_first={}хв, notified={}, reminder={}".format(
                mins_left, time_since_first // 60,
                s["notified_siege"], s.get("notified_reminder")
            ))
            if (
                s["notified_siege"]
                and not s.get("notified_reminder")
                and 0 < mins_left <= 25
                and time_since_first >= 90 * 60
            ):
                mins_display = max(0, mins_left)
                msg = SIEGE_REMINDER.format(
                    our_acc=o["our_acc"], nom=o["nom"],
                    mins=mins_display, name=fort_name,
                    attackers=attackers_str, time=siege_time_str,
                    url=page_url,
                )
                image = None
                if CARDS_ENABLED:
                    try:
                        image = build_card(
                            obj_type     = obj_type,
                            obj_name     = fort_name,
                            event_text   = SIEGE_REMINDER_CARD_TITLE.format(our_acc=o["our_acc"], mins=mins_display),
                            event_color  = C_GOLD,
                            owner_name   = OUR_CLAN,
                            owner_icon_url = (our.get("owner") or {}).get("image"),
                            attackers    = (our.get("siege_sides") or {}).get("attackers", []),
                            siege_time   = siege_time_str,
                            page_url     = page_url,
                        )
                        log.debug("build_card reminder: {}".format("OK" if image else "None"))
                    except Exception as e:
                        log.error("build_card reminder FAILED: {}".format(e))
                        import traceback; log.error(traceback.format_exc())
                if send_notification(msg, image):
                    s["notified_reminder"] = True
                else:
                    log.warning("TG нагадування не відправлено — спробуємо знову")

        elif not attackers and s.get("notified_siege"):
            now           = int(time.time())
            last_siege_at = s.get("last_siege_at", 0)
            if last_siege_at and now >= last_siege_at:
                log.info("Облога {} {} завершилась (час минув).".format(obj_type, fort_name))
            else:
                msg = SIEGE_CANCELLED.format(
                    our_acc=o["our_acc"], nom=o["nom"],
                    name=fort_name, url=page_url,
                )
                image = None
                if CARDS_ENABLED:
                    try:
                        image = build_card(
                            obj_type      = o["acc"],
                            obj_name      = fort_name,
                            event_text    = "Атаку відмінено",
                            event_color   = (60, 60, 80),
                            owner_name    = OUR_CLAN,
                            owner_icon_url = s.get("owner_image"),
                            attackers     = [],
                            siege_time    = None,
                            page_url      = page_url,
                        )
                    except Exception as e:
                        log.error("build_card cancelled FAILED: {}".format(e))
                send_notification(msg, image)
            s["notified_siege"]     = False
            s["last_attackers"]     = []
            s["last_siege_at"]      = 0
            s["siege_first_notify"] = 0
            s["notified_reminder"]  = False

    else:
        # Нас немає серед власників
        if s["had"] and not s.get("notified_lost"):
            fort_name = s.get("name") or "невідомий об'єкт"
            our_old = next((f for f in items if f.get("id") == s.get("id")), None)
            if our_old:
                new_owner = our_old.get("owner")
                new_owner_name = "NPC (без власника)" if new_owner is None else new_owner.get("name", "невідомо")
            else:
                new_owner_name = "невідомо"

            msg = OBJECT_LOST.format(
                acc_lost=o["acc_lost"], nom=o["nom"],
                name=fort_name, owner=new_owner_name, url=page_url,
            )
            image = None
            if CARDS_ENABLED:
                try:
                    image = build_card(
                        obj_type      = o["acc"],
                        obj_name      = fort_name,
                        event_text    = "{} втрачено!".format(o["acc_lost"]),
                        event_color   = (80, 80, 80),
                        owner_name    = new_owner_name,
                        owner_icon_url = (our_old.get("owner") or {}).get("image") if our_old else None,
                        attackers     = [],
                        siege_time    = None,
                        page_url      = page_url,
                    )
                except Exception as e:
                    log.error("build_card lost FAILED: {}".format(e))
            if send_notification(msg, image):
                s["had"]             = False
                s["notified_lost"]   = True
                s["notified_siege"]  = False
                s["last_attackers"]  = []
                s["last_siege_at"]   = 0
                s["siege_first_notify"] = 0
                s["notified_reminder"]  = False
            else:
                # TG не відправлено — скидаємо had але не notified_lost,
                # наступний цикл знову знайде що нас немає і спробує відправити
                log.warning("TG втрата {} не відправлено — спробуємо знову".format(obj_type))
                s["had"] = False

        elif not s["had"]:
            log.info("Клан {} не має {}. Чекаємо.".format(OUR_CLAN, obj_type))

    return s

# ─── Логіка: наші атаки на чужі об'єкти ─────────────────────────────────────
def process_our_attacks(attack_state, items, obj_key, page_url):
    """
    Шукає об'єкти де ми є серед атакуючих (але не власник).
    obj_key: 'fortress' або 'castle'.
    Повертає оновлений attack_state.
    """
    o = OBJ[obj_key]
    obj_type = o["acc"]
    current_ids = set()

    for item in items:
        attackers = get_attackers(item)
        if OUR_CLAN not in attackers:
            continue
        # Пропускаємо якщо ми є власником цього об'єкту
        owner = item.get("owner")
        if owner and owner.get("name") == OUR_CLAN:
            continue

        obj_id    = str(item["id"])
        obj_name  = item["name"]
        siege_at  = item.get("siege_at", 0)
        owner     = item.get("owner")
        siege_sides = item.get("siege_sides") or {}
        attacker_rows = siege_sides.get("attackers", []) if isinstance(siege_sides, dict) else []
        owner_name = owner["name"] if owner else "NPC"
        siege_time_str = format_time(siege_at)
        current_ids.add(obj_id)

        prev = attack_state.get(obj_id, {})

        # Новий запис або змінився час
        if not prev.get("notified") or siege_at != prev.get("siege_at", 0):
            msg = WE_ATTACK.format(
                acc=o["acc"], nom=o["nom"],
                name=obj_name, owner=owner_name,
                time=siege_time_str, url=page_url,
            )
            image = None
            if CARDS_ENABLED:
                try:
                    image = build_card(
                        obj_type      = o["acc"],
                        obj_name      = obj_name,
                        event_text    = "Атакуємо {acc}!".format(acc=o["acc"]),
                        event_color   = (26, 107, 138),  # синій — ми атакуємо
                        owner_name    = owner_name,
                        owner_icon_url = (item.get("owner") or {}).get("image"),
                        attackers     = attacker_rows,
                        siege_time    = siege_time_str,
                        page_url      = page_url,
                    )
                except Exception as e:
                    log.error("build_card we_attack FAILED: {}".format(e))
            if send_notification(msg, image):
                attack_state[obj_id] = {
                    "name":      obj_name,
                    "siege_at":  siege_at,
                    "notified":  True,
                    "owner_icon": (item.get("owner") or {}).get("image"),
                }
            else:
                log.warning("TG наша атака {} не відправлено".format(obj_name))

    # Знайти об'єкти з яких ми зникли (знялись з реги або облога пройшла)
    disappeared = set(attack_state.keys()) - current_ids
    now = int(time.time())
    to_delete = []
    for obj_id in disappeared:
        prev      = attack_state[obj_id]
        obj_name  = prev.get("name", "невідомо")
        siege_at  = prev.get("siege_at", 0)

        if siege_at and now >= siege_at:
            # Час пройшов — облога відбулась або завершилась, мовчимо
            log.info("Наша атака на {} {} — час минув, скидаємо.".format(obj_type, obj_name))
            to_delete.append(obj_id)
        else:
            # Знялись з реги до початку
            msg = WE_CANCELLED.format(
                nom=o["nom"], name=obj_name,
            )
            if send_telegram(msg):
                to_delete.append(obj_id)
                log.info("Клан {} знявся з реги атаки на {} {}.".format(OUR_CLAN, obj_type, obj_name))
            else:
                log.warning("TG знявся з реги не відправлено — спробуємо знову")

    for obj_id in to_delete:
        del attack_state[obj_id]

    return attack_state

# ─── Головний цикл перевірки ──────────────────────────────────────────────────
def check_and_notify():
    log.info("── Перевірка ──")
    try:
        _check_and_notify_inner()
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log.error("Помилка в циклі перевірки: {}\n{}".format(e, tb))
        send_debug(DEBUG_CYCLE_ERROR.format(error=str(e)[:300]))

def _check_and_notify_inner():
    state = load_state()

    # Мігруємо старий стан (якщо запускається вперше після оновлення)
    if "fortress" not in state:
        log.info("Мігруємо старий state.json до нової структури")
        new_state = _empty_state()
        # Переносимо дані старого формату якщо є
        new_state["fortress"]["had"]              = state.get("had_fortress", False)
        new_state["fortress"]["name"]             = state.get("fort_name")
        new_state["fortress"]["id"]               = state.get("fort_id")
        new_state["fortress"]["last_attackers"]   = state.get("last_attackers", [])
        new_state["fortress"]["last_siege_at"]    = state.get("last_siege_at", 0)
        new_state["fortress"]["notified_siege"]   = state.get("notified_siege", False)
        new_state["fortress"]["notified_lost"]    = state.get("notified_lost", False)
        new_state["fortress"]["siege_first_notify"] = state.get("siege_first_notify", 0)
        new_state["fortress"]["notified_reminder"] = state.get("notified_reminder", False)
        state = new_state

    # ── Запит 1: фортеці ──
    delay = random.uniform(1.0, 8.0)
    log.info("Затримка перед запитом фортець: {:.1f}с".format(delay))
    time.sleep(delay)
    fortress_items = fetch_page_data(FORTRESS_URL, "fortresses")

    # ── Пауза між запитами ──
    pause = random.randint(*BETWEEN_REQUESTS_DELAY)
    log.info("Пауза між запитами: {}с".format(pause))
    time.sleep(pause)

    # ── Запит 2: замки ──
    delay = random.uniform(1.0, 8.0)
    log.info("Затримка перед запитом замків: {:.1f}с".format(delay))
    time.sleep(delay)
    castle_items = fetch_page_data(CASTLE_URL, "castles")

    # ── Обробка фортець ──
    if fortress_items is not None:
        state["fortress"] = process_defence(
            state["fortress"], fortress_items, "fortress", FORTRESS_URL
        )
        state["our_fortress_attacks"] = process_our_attacks(
            state.get("our_fortress_attacks", {}), fortress_items, "fortress", FORTRESS_URL
        )

    # ── Обробка замків ──
    if castle_items is not None:
        state["castle"] = process_defence(
            state["castle"], castle_items, "castle", CASTLE_URL
        )
        state["our_castle_attacks"] = process_our_attacks(
            state.get("our_castle_attacks", {}), castle_items, "castle", CASTLE_URL
        )

    log.info(
        "Стан: фортеця={} ({}), замок={} ({}), наші атаки фортів={}, наші атаки замків={}".format(
            state["fortress"].get("name"),
            "є" if state["fortress"]["had"] else "немає",
            state["castle"].get("name"),
            "є" if state["castle"]["had"] else "немає",
            list(state.get("our_fortress_attacks", {}).keys()),
            list(state.get("our_castle_attacks", {}).keys()),
        )
    )
    save_state(state)

# ─── Polling / команди ───────────────────────────────────────────────────────
_last_update_id = 0

def build_status_card(state, obj_key, page_url):
    """Будує картку статусу для /status команди."""
    s = state.get(obj_key, {})
    if not s.get("had") or not s.get("name"):
        return None, None
    o = OBJ[obj_key]

    attackers_raw = []
    last_attackers = s.get("last_attackers", [])
    # last_attackers зберігаємо як список рядків, але build_card очікує [{name, image}]
    for a in last_attackers:
        if isinstance(a, dict):
            attackers_raw.append(a)
        else:
            attackers_raw.append({"name": str(a), "image": None})

    siege_at   = s.get("last_siege_at", 0)
    siege_time = format_time(siege_at) if siege_at else None

    o = OBJ[obj_key]
    if s.get("notified_siege") and attackers_raw:
        event_text  = STATUS_CARD_TITLE_SIEGE.format(nom=o["nom"])
        event_color = C_RED if CARDS_ENABLED else None
        names = ", ".join(
            a["name"] if isinstance(a, dict) else str(a)
            for a in last_attackers
        )
        caption = STATUS_SIEGE.format(
            nom=o["nom"], name=s["name"],
            attackers=names, time=siege_time or "?",
            url=page_url,
        )
    else:
        event_text  = STATUS_CARD_TITLE_PEACE.format(nom=o["nom"])
        event_color = (26, 107, 138) if CARDS_ENABLED else None
        caption = STATUS_PEACE.format(
            nom=o["nom"], name=s["name"],
            url=page_url,
        )

    image = None
    if CARDS_ENABLED and event_color:
        try:
            image = build_card(
                obj_type      = o["acc"],
                obj_name      = s["name"],
                event_text    = event_text,
                event_color   = event_color,
                owner_name    = OUR_CLAN,
                owner_icon_url = s.get("owner_image"),
                attackers     = attackers_raw,
                siege_time    = siege_time,
                page_url      = page_url,
            )
        except Exception as e:
            log.warning("build_card для статусу не вдалось: {}".format(e))

    return image, caption

def handle_status_command(chat_id):
    """Відповідає на /status — надсилає картки фортеці і замку."""
    log.info("Команда /status від chat_id={}".format(chat_id))
    state = load_state()

    sent_anything = False

    for obj_key, obj_type, page_url in [
        ("fortress", "fortress", FORTRESS_URL),
        ("castle",   "castle",   CASTLE_URL),
    ]:
        s = state.get(obj_key, {})
        if not s.get("had") or not s.get("name"):
            continue
        image, caption = build_status_card(state, obj_key, page_url)
        if caption:
            send_notification(caption, image, chat_id=str(chat_id))
            sent_anything = True

    if not sent_anything:
        send_telegram(
            STATUS_NO_OBJECT.format(clan=OUR_CLAN, acc="фортець і замків"),
            chat_id=str(chat_id)
        )

def handle_help_command(chat_id):
    send_telegram(HELP_TEXT, chat_id=str(chat_id))

def poll_updates():
    """Фоновий тред: отримує апдейти від TG і обробляє команди."""
    global _last_update_id
    url = "https://api.telegram.org/bot{}/getUpdates".format(TG_TOKEN)
    log.info("Polling запущено")

    while True:
        try:
            r = requests.get(
                url,
                params={"offset": _last_update_id + 1, "timeout": 30, "allowed_updates": ["message"]},
                timeout=35
            )
            r.raise_for_status()
            data = r.json()

            for update in data.get("result", []):
                _last_update_id = update["update_id"]
                msg = update.get("message", {})
                text    = msg.get("text", "").strip()
                chat_id = msg.get("chat", {}).get("id")

                if not text or not chat_id:
                    continue

                log.info("Отримано повідомлення: \'{}\' від {}".format(text, chat_id))

                if text.startswith("/status"):
                    handle_status_command(chat_id)
                elif text.startswith("/help"):
                    handle_help_command(chat_id)

        except requests.exceptions.Timeout:
            pass  # long polling таймаут — нормально, просто повторюємо
        except Exception as e:
            log.warning("Polling помилка: {}".format(e))
            time.sleep(5)

# ─── Точка входу ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # ── Перевірка налаштувань ──
    errors = []
    if TG_TOKEN == "YOUR_BOT_TOKEN_HERE" or not TG_TOKEN.strip():
        errors.append("  TG_TOKEN не вказано в config.py")
    if TG_CHAT == "YOUR_CHAT_ID_HERE" or not TG_CHAT.strip():
        errors.append("  TG_CHAT не вказано в config.py")
    if TG_CHAT_DEBUG == "YOUR_DEBUG_CHAT_ID_HERE" or not TG_CHAT_DEBUG.strip():
        errors.append("  TG_CHAT_DEBUG не вказано в config.py — дебаг повідомлення вимкнено")

    if errors:
        critical = [e for e in errors if "TG_TOKEN" in e or "TG_CHAT не" in e]
        warnings = [e for e in errors if e not in critical]
        for w in warnings:
            log.warning("УВАГА: {}".format(w.strip()))
        if critical:
            log.critical("=" * 50)
            log.critical("БОТА НЕ МОЖНА ЗАПУСТИТИ — не вказані обов'язкові параметри:")
            for e in critical:
                log.critical(e)
            log.critical("Відкрий config.py і заповни TG_TOKEN та TG_CHAT.")
            log.critical("=" * 50)
            raise SystemExit(1)

    log.info("=" * 50)
    log.info("Scryde Fortress & Castle Bot запущено")
    log.info("Клан: {}".format(OUR_CLAN))
    log.info("Інтервал: {}-{} хвилин (рандом)".format(CHECK_INTERVAL_MIN // 60, CHECK_INTERVAL_MAX // 60))
    log.info("=" * 50)

    send_debug(DEBUG_BOT_STARTED.format(clan=OUR_CLAN))

    # Запускаємо polling в фоновому треді
    poll_thread = threading.Thread(target=poll_updates, daemon=True, name="TG-Polling")
    poll_thread.start()
    log.info("Polling тред запущено")

    try:
        check_and_notify()

        while True:
            interval = random.randint(CHECK_INTERVAL_MIN, CHECK_INTERVAL_MAX)
            log.info("Наступна перевірка через {} хв {} с".format(interval // 60, interval % 60))
            time.sleep(interval)
            check_and_notify()

    except KeyboardInterrupt:
        log.info("Бот зупинений вручну (KeyboardInterrupt)")
        send_debug(DEBUG_BOT_STOPPED)

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        log.critical("КРИТИЧНА ПОМИЛКА: {}\n{}".format(e, tb))
        send_debug(DEBUG_CRITICAL.format(error=str(e)[:300]))
        raise
