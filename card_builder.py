#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Генерує картку-зображення для TG повідомлень.
Потребує: pip install Pillow
"""

import io
import os
import re
import logging
import requests

log = logging.getLogger(__name__)

try:
    from PIL import Image, ImageDraw, ImageFont
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    log.warning("Pillow не встановлено. pip install Pillow")

# ─── Розміри ─────────────────────────────────────────────────────────────────
CARD_W    = 420
ICON_W = 24  # оригінальний розмір іконки клану L2
ICON_H = 12
PAD       = 10

# ─── Кольори ─────────────────────────────────────────────────────────────────
C_BG     = (10,  28,  42)
C_TEXT1  = (232, 244, 248)
C_TEXT2  = (140, 195, 215)
C_GOLD   = (210, 175,  75)
C_WHITE  = (255, 255, 255)
C_TRANSP = (0, 0, 0, 0)
C_RED    = (180,  40,  30)
C_BLUE   = (26,  107, 138)

# ─── Шрифти ──────────────────────────────────────────────────────────────────
# DejaVu гарантовано підтримує кирилицю
_FONT_CANDIDATES = [
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans{}.ttf",      ""),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans{}.ttf",      "-Bold"),
    ("/usr/share/fonts/truetype/freefont/FreeSans{}.ttf",      ""),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-{}.ttf", "Regular"),
]

_font_cache = {}

def font(size, bold=False):
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]
    suffix = "-Bold" if bold else ""
    paths = [
        "/usr/share/fonts/dejavu/DejaVuSans{}.ttf".format(suffix),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans{}.ttf".format(suffix),
        "/usr/share/fonts/truetype/freefont/FreeSans{}.ttf".format(suffix),
        "/usr/share/fonts/truetype/liberation/LiberationSans{}-Regular.ttf".format(suffix),
        "/usr/share/fonts/truetype/crosextra/Carlito{}.ttf".format(suffix),
    ]
    for p in paths:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, size)
                _font_cache[key] = f
                return f
            except Exception:
                pass
    # Якщо нічого не знайшли — load_default (не підтримує кирилицю але хоч не крашить)
    log.warning("Не знайдено TTF шрифт з кирилицею! Встановіть: apt-get install fonts-dejavu")
    f = ImageFont.load_default(size=size)
    _font_cache[key] = f
    return f

# ─── Кеш зображень ───────────────────────────────────────────────────────────
_img_cache = {}

# Referer обов'язковий — CDN може блокувати без нього
FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer":    "https://ua.scryde.game/",
    "Accept":     "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}

def fetch_image(url, size=None):
    if not url:
        return None
    key = "{}@{}".format(url, size)
    if key in _img_cache:
        return _img_cache[key]
    try:
        r = requests.get(url, headers=FETCH_HEADERS, timeout=8)
        r.raise_for_status()
        img = Image.open(io.BytesIO(r.content)).convert("RGBA")
        if size:
            img = img.resize(size, Image.LANCZOS)
        _img_cache[key] = img
        log.info("Завантажено зображення: {}".format(url))
        return img
    except Exception as e:
        log.warning("fetch_image {}: {}".format(url, e))
        _img_cache[key] = None
        return None

def clan_icon(url):
    """Завантажує іконку клану 24x12 (оригінальний розмір L2). Або None."""
    img = fetch_image(url)
    if img:
        return img.resize((ICON_W, ICON_H), Image.LANCZOS).convert("RGBA")
    return None

# ─── URL фонових зображень ───────────────────────────────────────────────────
def fortress_bg_url(name):
    key = re.sub(r'\s+fortress$', '', name, flags=re.IGNORECASE).lower().strip().replace(' ', '_')
    return "https://frontend-static-eu.scrydecdn.com/static/images/rankings/fortresses/{}.webp".format(key)

def castle_bg_url(name):
    key = name.lower().strip().replace(' ', '_')
    return "https://frontend-static-eu.scrydecdn.com/static/images/rankings/castles/{}.webp".format(key)

# ─── Малювання рядка: [іконка] [текст] ───────────────────────────────────────
def draw_clan_row(card, draw, x, y, icon_img, name, name_font, color=C_TEXT1):
    """Малює [іконка 24x12] [назва] в рядку. Повертає x після тексту."""
    ix = x
    if icon_img:
        icon_y = y + 2
        card.paste(icon_img, (ix, icon_y), icon_img)
        ix += ICON_W + 4
    draw.text((ix, y), name, font=name_font, fill=color)
    bbox = name_font.getbbox(name)
    return ix + (bbox[2] - bbox[0]) + 12

# ─── Розмір рядка клану ─────────────────────────────────────────────────────
ROW_H = 20  # висота одного рядка з кланом (іконка 12px + відступи)

# ─── Головна функція ─────────────────────────────────────────────────────────
def build_card(
    obj_type,
    obj_name,
    event_text,
    event_color,
    owner_name,
    owner_icon_url,
    attackers,       # [{"name": "...", "image": "..."}, ...]
    siege_time,
    page_url,
):
    if not PILLOW_AVAILABLE:
        return None

    # ── Розраховуємо висоту динамічно ──
    # Фіксовані блоки: заголовок + назва + час + роздільник + лейбли
    HEADER_H  = 30
    INFO_H    = 48   # назва + час облоги
    SEP_H     = 12
    LABEL_H   = 16
    FOOTER_H  = 18
    # Рядки кланів: власник (1) + атакуючі (N)
    n_rows    = 1 + len(attackers)
    rows_h    = n_rows * ROW_H + (n_rows - 1) * 4  # рядки + відступи між ними
    card_h    = HEADER_H + INFO_H + SEP_H + LABEL_H + rows_h + FOOTER_H + PAD

    # ── Фон ──
    card = Image.new("RGBA", (CARD_W, card_h), C_BG)

    is_castle = "замок" in obj_type.lower()
    bg_url    = castle_bg_url(obj_name) if is_castle else fortress_bg_url(obj_name)
    bg_img    = fetch_image(bg_url, (CARD_W, card_h))
    if bg_img:
        card.paste(bg_img.convert("RGBA"), (0, 0))
        ov = Image.new("RGBA", (CARD_W, card_h), (8, 22, 34, 165))
        card.paste(ov, (0, 0), ov)

    d = ImageDraw.Draw(card)

    # ── Заголовок ──
    d.rectangle([(0, 0), (CARD_W, HEADER_H)], fill=event_color + (225,))
    d.text((PAD, 7), event_text, font=font(16, bold=True), fill=C_WHITE)

    # ── Назва об'єкту ──
    y = HEADER_H + 6
    d.text((PAD, y), obj_name, font=font(15, bold=True), fill=C_TEXT1)

    # ── Час облоги ──
    y += 18
    if siege_time:
        d.text((PAD, y), "Облога:  {}".format(siege_time),
               font=font(13, bold=True), fill=C_GOLD)

    # ── Роздільник ──
    y += SEP_H + 8
    d.line([(PAD, y), (CARD_W - PAD, y)], fill=(26, 107, 138, 100), width=1)

    # ── Ліва і права колонки ──
    col_left  = PAD
    col_right = CARD_W // 2 + PAD

    y += 4
    d.text((col_left, y), "Власник", font=font(11), fill=C_TEXT2)
    if attackers:
        d.text((col_right, y), "Атакуючі", font=font(11), fill=C_TEXT2)

    y += LABEL_H

    # ── Власник (іконка + ім'я) — ліва колонка ──
    owner_ico = clan_icon(owner_icon_url)
    draw_clan_row(card, d, col_left, y, owner_ico, owner_name or "NPC",
                  font(14, bold=True), C_TEXT1)

    # ── Атакуючі — права колонка, вертикально ──
    atk_y = y
    for atk in attackers:
        atk_name = atk.get("name", "?") if isinstance(atk, dict) else str(atk)
        atk_url  = atk.get("image")      if isinstance(atk, dict) else None
        atk_ico  = clan_icon(atk_url)
        draw_clan_row(card, d, col_right, atk_y, atk_ico,
                      atk_name, font(14, bold=True), C_TEXT1)
        atk_y += ROW_H + 4
    y = max(y, atk_y)  # беремо більший y для footer

    # ── Footer ──
    footer_y = card_h - FOOTER_H
    d.rectangle([(0, footer_y), (CARD_W, card_h)], fill=(0, 0, 0, 130))
    d.text((PAD, footer_y + 3), page_url, font=font(10), fill=C_TEXT2)

    buf = io.BytesIO()
    card.convert("RGB").save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.read()
