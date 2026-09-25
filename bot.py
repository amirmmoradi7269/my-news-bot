#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات رایگان تلگرامی برای جمع‌آوری خودکار اخبار و پست در کانال
------------------------------------------------------------
این برنامه هیچ هزینه‌ای ندارد. طوری طراحی شده که روی GitHub Actions
اجرا شود (سرورهای رایگان گیت‌هاب) — یعنی نیازی نیست گوشی یا کامپیوترتان
همیشه روشن باشد؛ گیت‌هاب خودش هر چند دقیقه یک‌بار این کد را اجرا می‌کند.

کاری که هر بار اجرا انجام می‌دهد:
    ۱. چند سایت خبری را چک می‌کند.
    ۲. اگر خبر جدیدی پیدا کرد، عنوان و خلاصه‌اش را می‌خواند.
    ۳. اگر خبر مربوط به «جنگ»، «اخبار مهم ایران»، «تعطیلی» یا
       «سخنان افراد مهم» بود، آن را در چند خط در کانال تلگرام پست می‌کند.
    ۴. اگر خبر مرتبط نبود، آن را نادیده می‌گیرد.
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
# این دو مقدار از GitHub Secrets خوانده می‌شوند (امن‌تر از نوشتن مستقیم).
# اگر می‌خواهید روی گوشی/کامپیوتر خودتان تست کنید، می‌توانید همین‌جا
# مستقیم مقدارشان را بنویسید.
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "اینجا-توکن-ربات-را-بگذارید")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@یوزرنیم_کانال_شما")

# ============================================================
# بخش ۲: منابع خبری (نیازی به تغییر ندارد، ولی می‌توانید کم/زیاد کنید)
# ============================================================

RSS_FEEDS = [
    "https://www.isna.ir/rss",
    "https://www.mehrnews.com/rss",
    "https://www.khabaronline.ir/rss",
    "https://www.tasnimnews.com/fa/rss/feed/0/7/0/",
]

# حداکثر تعداد پست در هر بار اجرا (برای جلوگیری از سیل پیام در اولین اجرا)
MAX_POSTS_PER_RUN = 5

# ============================================================
# بخش ۳: کلمات کلیدی — با این‌ها تشخیص می‌دهیم خبر مهم هست یا نه
# (می‌توانید کلمه اضافه یا کم کنید)
# ============================================================

CATEGORIES = {
    "⚔️ جنگ": [
        "جنگ", "حمله", "موشک", "بمباران", "درگیری نظامی",
        "آتش‌بس", "تجاوز نظامی", "حمله نظامی", "پهپاد", "انفجار",
    ],
    "📌 خبر مهم ایران": [
        "رئیس‌جمهور", "رهبر انقلاب", "مجلس شورای اسلامی", "بانک مرکزی",
        "وزارت خارجه", "شورای امنیت", "تحریم", "دولت ایران", "قوه قضاییه",
    ],
    "📅 تعطیلی": [
        "تعطیل شد", "تعطیلی مدارس", "تعطیل رسمی", "تعطیلی ادارات",
        "تعطیلی بازار", "تعطیلی دانشگاه‌ها", "روز تعطیل",
    ],
    "🗣️ سخنان مهم": [
        "اعلام کرد", "هشدار داد", "تاکید کرد", "اظهار داشت", "خبر داد",
        "وزیر گفت", "سخنگو گفت", "رئیس‌جمهور گفت",
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
    """خواندن لینک‌های قبلاً پست‌شده، تا خبر تکراری پست نشود."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            log.warning("فایل وضعیت خراب بود، از صفر شروع می‌کنیم.")
    return set()


def save_posted_links(links):
    """ذخیره لینک‌های پست‌شده."""
    trimmed = list(links)[-2000:]
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def clean_html(raw_html: str) -> str:
    """حذف تگ‌های HTML از متن خبر."""
    text = re.sub(r"<[^>]+>", "", raw_html or "")
    return html.unescape(text).strip()


def find_category(title: str, summary: str):
    """
    چک می‌کند آیا خبر شامل کلمات کلیدی یکی از دسته‌هاست یا نه.
    اگر بود، اسم دسته را برمی‌گرداند؛ وگرنه None.
    """
    full_text = f"{title} {summary}"
    for category_name, keywords in CATEGORIES.items():
        for keyword in keywords:
            if keyword in full_text:
                return category_name
    return None


def format_message(title: str, summary: str, category: str, link: str, source_title: str) -> str:
    """ساخت متن پیامی که در کانال پست می‌شود (چند خط خلاصه)."""
    if len(summary) > 350:
        summary = summary[:350].rsplit(" ", 1)[0] + "..."

    message = f"{category}\n"
    message += f"<b>{html.escape(title)}</b>\n\n"
    if summary:
        message += f"{html.escape(summary)}\n\n"
    message += f"🔗 <a href=\"{link}\">ادامه خبر</a>\n"
    message += f"منبع: {html.escape(source_title)}"
    return message


def send_to_channel(text: str) -> bool:
    """ارسال پیام به کانال تلگرام."""
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
    """یک بار همه سایت‌های خبری را چک می‌کند."""
    new_posts_count = 0

    for feed_url in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:
            log.error(f"خطا در خواندن {feed_url}: {e}")
            continue

        if parsed.bozo and not parsed.entries:
            log.warning(f"این سایت قابل خواندن نبود: {feed_url}")
            continue

        source_title = parsed.feed.get("title", feed_url)
        entries = list(reversed(parsed.entries))  # قدیمی‌ترین اول، تا ترتیب درست باشد

        for entry in entries:
            link = entry.get("link")
            if not link or link in posted_links:
                continue

            if new_posts_count >= MAX_POSTS_PER_RUN:
                log.info("به سقف تعداد پست در این اجرا رسیدیم؛ بقیه در اجرای بعدی پست می‌شوند.")
                save_posted_links(posted_links)
                return posted_links

            title = clean_html(entry.get("title", "بدون عنوان"))
            summary = clean_html(entry.get("summary", ""))

            category = find_category(title, summary)
            posted_links.add(link)  # این خبر را بررسی‌شده علامت می‌زنیم (چه پست شود چه نشود)

            if category is None:
                continue  # مرتبط نبود، رد شو

            message = format_message(title, summary, category, link, source_title)
            if send_to_channel(message):
                log.info(f"پست شد [{category}]: {title[:60]}")
                new_posts_count += 1
            else:
                log.warning(f"پست نشد: {link}")

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
