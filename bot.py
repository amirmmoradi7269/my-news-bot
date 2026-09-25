#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات رایگان تلگرامی برای جمع‌آوری خودکار اخبار و پست در کانال
------------------------------------------------------------
این برنامه هیچ هزینه‌ای ندارد. روی GitHub Actions اجرا می‌شود.

هر بار اجرا:
    ۱. چند خبرگزاری معتبر ایرانی، بین‌المللی و عبری‌زبان را چک می‌کند.
    ۲. اگر خبر جدیدی پیدا کرد، عنوان و خلاصه‌اش را می‌خواند.
    ۳. اگر خبر مربوط به «جنگ»، «اخبار مهم ایران»، «تعطیلی» یا
       «سخنان افراد مهم» بود، آن را پست می‌کند.
    ۴. فقط یک خبر در هر اجرا پست می‌شود، تا پیام‌ها پشت‌سرهم نباشند
       (زمان‌بندی فاصله بین پست‌ها را فایل news.yml کنترل می‌کند).
"""

import json
import os
import re
import html
import logging
import requests
import feedparser

# ============================================================
# بخش ۱: تنظیمات
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "اینجا-توکن-ربات-را-بگذارید")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@یوزرنیم_کانال_شما")

# ============================================================
# بخش ۲: منابع خبری
# ============================================================

RSS_FEEDS = [
    # ایرانی
    "https://www.isna.ir/rss",
    "https://www.mehrnews.com/rss",
    "https://www.khabaronline.ir/rss",
    "https://www.tasnimnews.com/fa/rss/feed/0/7/0/",
    # بین‌المللی
    "http://rss.cnn.com/rss/cnn_topstories.rss",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    # عبری‌زبان / اسرائیلی
    "https://www.timesofisrael.com/feed/",
    "https://www.ynet.co.il/Integration/StoryRss2.xml",
]

# فقط یک خبر در هر اجرا پست می‌شود (برای رعایت فاصله زمانی بین پست‌ها)
MAX_POSTS_PER_RUN = 1

# ============================================================
# بخش ۳: کلمات کلیدی (فارسی + انگلیسی + عبری)
# ============================================================

CATEGORIES = {
    "⚔️ جنگ": [
        # فارسی
        "جنگ", "حمله", "موشک", "بمباران", "درگیری نظامی", "آتش‌بس",
        "تجاوز نظامی", "حمله نظامی", "پهپاد", "انفجار",
        # انگلیسی
        "war", "attack", "missile", "airstrike", "air strike", "bombing",
        "military conflict", "ceasefire", "invasion", "drone strike",
        "explosion", "strike on", "troops",
        # عبری
        "מלחמה", "תקיפה", "טיל", "הפצצה", "לחימה", "הפוגה", "פלישה",
        "רחפן", "פיצוץ",
    ],
    "📌 خبر مهم ایران": [
        # فارسی
        "رئیس‌جمهور", "رهبر انقلاب", "مجلس شورای اسلامی", "بانک مرکزی",
        "وزارت خارجه", "شورای امنیت", "تحریم", "دولت ایران", "قوه قضاییه",
        # انگلیسی (مرتبط با ایران)
        "iran's president", "iranian president", "iranian government",
        "iran nuclear", "sanctions on iran", "tehran", "iranian parliament",
        "iran's supreme leader", "irgc", "revolutionary guard",
        # عبری
        "איראן", "טהראן", "נשיא איראן", "משמרות המהפכה",
    ],
    "📅 تعطیلی": [
        # فارسی
        "تعطیل شد", "تعطیلی مدارس", "تعطیل رسمی", "تعطیلی ادارات",
        "تعطیلی بازار", "تعطیلی دانشگاه‌ها", "روز تعطیل",
        # انگلیسی
        "schools closed", "offices closed", "public holiday declared",
        "declared a holiday", "markets closed",
        # عبری
        "חג", "בתי הספר נסגרו", "יום שבתון",
    ],
    "🗣️ سخنان مهم": [
        # فارسی
        "اعلام کرد", "هشدار داد", "تاکید کرد", "اظهار داشت", "خبر داد",
        "وزیر گفت", "سخنگو گفت", "رئیس‌جمهور گفت",
        # انگلیسی
        "president said", "prime minister said", "said in a statement",
        "warned that", "announced that", "spokesperson said",
        # عبری
        "אמר הנשיא", "ראש הממשלה אמר", "הודיע",
    ],
}

# ============================================================
# از این خط به پایین، نیازی به تغییر چیزی نیست
# ============================================================

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "posted_links.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("news_bot")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def load_posted_links():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            log.warning("فایل وضعیت خراب بود، از صفر شروع می‌کنیم.")
    return set()


def save_posted_links(links):
    trimmed = list(links)[-3000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def clean_html(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw_html or "")
    return html.unescape(text).strip()


def find_category(title: str, summary: str):
    full_text = f"{title} {summary}".lower()
    for category_name, keywords in CATEGORIES.items():
        for keyword in keywords:
            if keyword.lower() in full_text:
                return category_name
    return None


def format_message(title: str, summary: str, category: str, link: str) -> str:
    """
    پیام خلاصه: دسته + عنوان + خلاصه چندخطی + لینک خام (بدون منبع، بدون متن اضافه دور لینک).
    """
    if len(summary) > 350:
        summary = summary[:350].rsplit(" ", 1)[0] + "..."

    message = f"{category}\n"
    message += f"<b>{html.escape(title)}</b>\n\n"
    if summary:
        message += f"{html.escape(summary)}\n\n"
    message += link  # لینک خام؛ تلگرام خودش آن را قابل‌کلیک می‌کند
    return message


def send_to_channel(text: str) -> bool:
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    try:
        resp = requests.post(url, data=payload, timeout=20)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        log.error(f"خطا در ارسال پیام به تلگرام: {e}")
        if hasattr(e, "response") and e.response is not None:
            log.error(f"پاسخ تلگرام: {e.response.text}")
        return False


def check_feeds_once(posted_links: set) -> set:
    new_posts_count = 0

    for feed_url in RSS_FEEDS:
        if new_posts_count >= MAX_POSTS_PER_RUN:
            break

        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:
            log.error(f"خطا در خواندن {feed_url}: {e}")
            continue

        if parsed.bozo and not parsed.entries:
            log.warning(f"این سایت قابل خواندن نبود: {feed_url}")
            continue

        entries = list(reversed(parsed.entries))

        for entry in entries:
            link = entry.get("link")
            if not link or link in posted_links:
                continue

            if new_posts_count >= MAX_POSTS_PER_RUN:
                break

            title = clean_html(entry.get("title", "بدون عنوان"))
            summary = clean_html(entry.get("summary", ""))

            category = find_category(title, summary)

            if category is None:
                posted_links.add(link)  # نامرتبط؛ دیگر بررسی نشود
                continue

            message = format_message(title, summary, category, link)
            if send_to_channel(message):
                log.info(f"پست شد [{category}]: {title[:60]}")
                posted_links.add(link)
                new_posts_count += 1
            else:
                log.warning(f"پست نشد: {link}")
                # لینک را علامت نمی‌زنیم تا در اجرای بعد دوباره امتحان شود

    save_posted_links(posted_links)
    return posted_links


def main():
    if "اینجا" in BOT_TOKEN:
        log.error("BOT_TOKEN تنظیم نشده (نه در فایل و نه در Secrets گیت‌هاب).")
        return
    if "یوزرنیم_کانال_شما" in CHANNEL_ID:
        log.error("CHANNEL_ID تنظیم نشده (نه در فایل و نه در Secrets گیت‌هاب).")
        return

    log.info("شروع بررسی اخبار...")
    posted_links = load_posted_links()
    log.info(f"{len(posted_links)} خبر قبلاً بررسی‌شده بارگذاری شد.")

    posted_links = check_feeds_once(posted_links)

    log.info("بررسی این دور تمام شد.")


if __name__ == "__main__":
    main()
