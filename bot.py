#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات رایگان تلگرامی — چک مداوم اخبار + پست با فاصله‌ی ثابت
------------------------------------------------------------
این ربات به‌صورت پیوسته (بدون وقفه) چند خبرگزاری را چک می‌کند، اما برای
اینکه پیام‌ها پشت‌سرهم در کانال ظاهر نشوند، بین هر پست حداقل ۷ دقیقه فاصله
می‌اندازد.

چون سرویس رایگان GitHub Actions هر اجرا را حداکثر تا ۶ ساعت اجازه می‌دهد،
این کد خودش را بعد از حدود ۵ ساعت و ۴۰ دقیقه به‌آرامی متوقف می‌کند و فایل
news.yml طوری تنظیم شده که هر ۶ ساعت دوباره از نو شروعش کند — یعنی در عمل
تقریباً همیشه در حال اجراست.
"""

import json
import os
import re
import html
import time
import logging
import subprocess
import requests
import feedparser
from deep_translator import GoogleTranslator, MyMemoryTranslator

# ============================================================
# بخش ۱: تنظیمات
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "اینجا-توکن-ربات-را-بگذارید")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "@یوزرنیم_کانال_شما")

CHECK_INTERVAL_SECONDS = 30          # هر چند ثانیه سایت‌ها را چک کند (تقریباً لحظه‌ای)
MIN_SECONDS_BETWEEN_POSTS = 7 * 60   # حداقل فاصله بین دو پست: ۷ دقیقه

# حداکثر مدت زمان اجرای مداوم (کمی کمتر از سقف ۶ ساعته گیت‌هاب)
MAX_RUN_SECONDS = int(os.environ.get("TEST_DURATION_SECONDS") or (5 * 3600 + 40 * 60))

# ============================================================
# بخش ۲: منابع خبری
# ============================================================

RSS_FEEDS = [
    # فارسی‌زبان مستقل (غیروابسته به جمهوری اسلامی) — اول این‌ها چک می‌شوند
    "https://feeds.bbci.co.uk/persian/rss.xml",
    "https://www.rferl.org/api/z-oiil-vomx-tpergmp",  # رادیو فردا (بخش ایران رادیو فردا/آزادی)
    # ایران‌وایر (آزمایشی — لینک رسمی تایید نشد، اگر خطا داد حذفش کنید)
    "https://iranwire.com/en/feed/",
    # ایران‌اینترنشنال (آزمایشی — لینک RSS رسمی این سایت پیدا/تایید نشد،
    # اگر در لاگ‌های Actions خطا داد، همین خط را حذف کنید)
    "https://www.iranintl.com/en/rss",
    # خاورمیانه
    "https://www.aljazeera.com/xml/rss/all.xml",
    # عبری‌زبان / اسرائیلی
    "https://www.timesofisrael.com/feed/",
    "https://www.ynet.co.il/Integration/StoryRss2.xml",
    "https://www.jpost.com/rss/rssfeedsfrontpage.aspx",
    # آمریکایی (آخرین اولویت)
    "http://rss.cnn.com/rss/cnn_topstories.rss",
    "http://feeds.foxnews.com/foxnews/latest?format=xml",
    "http://feeds.nbcnews.com/feeds/topstories",
    "https://www.cbsnews.com/latest/rss/main",  # CBS News
    "https://feeds.a.dj.com/rss/RSSWorldNews.xml",  # وال‌استریت‌ژورنال (فقط تیتر، چون محتوای اصلی پولیه)
]

# ============================================================
# بخش ۳: کلمات کلیدی (فارسی + انگلیسی + عبری)
# ============================================================

CATEGORIES = {
    "🇮🇷 ایران": [
        # فارسی
        "رئیس‌جمهور", "رهبر انقلاب", "مجلس شورای اسلامی", "بانک مرکزی",
        "وزارت خارجه", "شورای امنیت", "تحریم", "دولت ایران", "قوه قضاییه",
        "سپاه پاسداران", "سپاه", "قرارگاه خاتم‌الانبیا", "خاتم‌الانبیا",
        "نیروی قدس", "بسیج", "نمایندگان مجلس",
        # انگلیسی
        "iran's president", "iranian president", "iranian government",
        "iran nuclear", "sanctions on iran", "tehran", "iranian parliament",
        "iran's supreme leader", "irgc", "revolutionary guard",
        "khatam al-anbia", "quds force", "basij",
        # عبری
        "איראן", "טהראן", "נשיא איראן", "משמרות המהפכה",
    ],
    "⚔️ جنگ و فعالیت نظامی": [
        # فارسی
        "جنگ", "حمله", "موشک", "بمباران", "درگیری نظامی", "آتش‌بس",
        "تجاوز نظامی", "حمله نظامی", "پهپاد", "انفجار", "ارتش",
        "نیروی نظامی", "رزمایش", "تجهیزات نظامی", "پایگاه نظامی",
        # انگلیسی
        "war", "attack", "missile", "airstrike", "air strike", "bombing",
        "military conflict", "ceasefire", "invasion", "drone strike",
        "explosion", "strike on", "troops", "military", "army", "navy",
        "air force", "military exercise", "military base", "arms deal",
        "weapons shipment",
        # عبری
        "מלחמה", "תקיפה", "טיל", "הפצצה", "לחימה", "הפוגה", "פלישה",
        "רחפן", "פיצוץ", "צבא", "כוחות צבאיים", "תרגיל צבאי", "בסיס צבאי",
    ],
    "🏛️ نهادهای حکومتی مهم": [
        # فارسی
        "کاخ سفید", "پنتاگون", "کنگره آمریکا", "وزارت دفاع آمریکا",
        "کابینه اسرائیل", "کابینه امنیتی اسرائیل", "ستاد ارتش اسرائیل",
        "کرملین", "دولت چین", "حزب کمونیست چین",
        # انگلیسی
        "white house", "pentagon", "us congress", "us defense secretary",
        "israeli cabinet", "israeli security cabinet", "idf general staff",
        "kremlin", "chinese government", "chinese communist party",
        # عبری
        "הבית הלבן", "הפנטגון", "הקבינט הביטחוני", "קרמלין",
    ],
    "🤖 هوش مصنوعی": [
        "هوش مصنوعی",
        "artificial intelligence", "ai", "chatgpt", "openai", "machine learning",
        "ai model", "generative ai",
        "בינה מלאכותית",
    ],
    "🗣️ اظهارات مقامات ارشد": [
        # فارسی
        "رئیس‌جمهور گفت", "نخست‌وزیر گفت", "وزیر دفاع گفت", "وزیر جنگ گفت",
        "اعلام کرد", "هشدار داد", "تاکید کرد", "اظهار داشت",
        # انگلیسی
        "president said", "prime minister said", "defense minister said",
        "war minister said", "foreign minister said", "said in a statement",
        "warned that", "announced that", "cabinet member",
        "putin", "xi jinping", "netanyahu", "khamenei", "zelensky",
        # عبری
        "אמר הנשיא", "ראש הממשלה אמר", "שר הביטחון אמר", "הודיע",
        "נתניהו", "פוטין", "זלנסקי",
    ],
    "🗽 ترامپ": [
        "trump", "donald trump", "president trump", "trump said",
        "trump announced", "trump warned", "trump administration",
        "טראמפ",
    ],
}

# ============================================================
# از این خط به پایین، نیازی به تغییر چیزی نیست
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSTED_FILE = os.path.join(BASE_DIR, "posted_links.json")
LAST_POST_FILE = os.path.join(BASE_DIR, "last_post_time.json")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("news_bot")

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"


def load_posted_links():
    if os.path.exists(POSTED_FILE):
        try:
            with open(POSTED_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, OSError):
            log.warning("فایل وضعیت خراب بود، از صفر شروع می‌کنیم.")
    return set()


def save_posted_links(links):
    trimmed = list(links)[-4000:]
    with open(POSTED_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, ensure_ascii=False, indent=2)


def load_last_post_time() -> float:
    if os.path.exists(LAST_POST_FILE):
        try:
            with open(LAST_POST_FILE, "r", encoding="utf-8") as f:
                return json.load(f).get("last_post_unix", 0)
        except (json.JSONDecodeError, OSError):
            pass
    return 0.0


def save_last_post_time(ts: float):
    with open(LAST_POST_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_post_unix": ts}, f)


def git_push_state():
    """ذخیره‌ی وضعیت فعلی در خود مخزن گیت‌هاب، تا بعد از هر اجرای جدید از دست نرود."""
    try:
        subprocess.run(["git", "config", "user.name", "news-bot"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "news-bot@users.noreply.github.com"],
                        check=True, capture_output=True)
        subprocess.run(["git", "add", "posted_links.json", "last_post_time.json"],
                        check=True, capture_output=True)
        diff = subprocess.run(["git", "diff", "--staged", "--quiet"])
        if diff.returncode != 0:
            subprocess.run(["git", "commit", "-m", "update state"], check=True, capture_output=True)
            subprocess.run(["git", "push"], check=True, capture_output=True)
            log.info("وضعیت ذخیره و push شد.")
    except subprocess.CalledProcessError as e:
        log.warning(f"ذخیره‌ی وضعیت روی گیت‌هاب ناموفق بود: {e}")


def clean_html(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw_html or "")
    text = html.unescape(text).strip()
    text = re.sub(r"https?://\S+", "", text)  # حذف هر لینک خامی که در متن باشد
    return text.strip()


def translate_to_persian(text: str) -> str:
    """
    ترجمه‌ی رایگان متن به فارسی. اول گوگل امتحان می‌شود؛ اگر جواب نداد
    (مثلاً به‌خاطر محدودیت IP سرورهای گیت‌هاب)، سرویس دوم امتحان می‌شود.
    اگر هیچ‌کدام جواب نداد، متن اصلی برگردانده می‌شود.
    """
    if not text:
        return text

    try:
        result = GoogleTranslator(source="auto", target="fa").translate(text)
        if result and result.strip():
            return result
    except Exception as e:
        log.warning(f"ترجمه با گوگل ناموفق بود: {e}")

    try:
        result = MyMemoryTranslator(source="en-US", target="fa-IR").translate(text)
        if result and result.strip():
            log.info("ترجمه با سرویس دوم (MyMemory) انجام شد.")
            return result
    except Exception as e:
        log.warning(f"ترجمه با سرویس دوم هم ناموفق بود: {e}")

    log.warning("هر دو سرویس ترجمه شکست خوردند؛ متن اصلی (غیرفارسی) پست می‌شود.")
    return text


def find_category(title: str, summary: str):
    full_text = f"{title} {summary}".lower()
    for category_name, keywords in CATEGORIES.items():
        for keyword in keywords:
            pattern = r"\b" + re.escape(keyword.strip().lower()) + r"\b"
            if re.search(pattern, full_text):
                return category_name
    return None


def format_message(title: str, summary: str, category: str) -> str:
    if len(summary) > 350:
        summary = summary[:350].rsplit(" ", 1)[0] + "..."
    message = f"<b>{html.escape(title)}</b>\n\n"
    if summary:
        message += html.escape(summary)
    return message


def send_to_channel(text: str) -> bool:
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
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


def find_next_candidate(posted_links: set):
    """یک خبر مرتبط و پست‌نشده پیدا می‌کند (اگر باشد)."""
    for feed_url in RSS_FEEDS:
        try:
            parsed = feedparser.parse(feed_url)
        except Exception as e:
            log.error(f"خطا در خواندن {feed_url}: {e}")
            continue

        if parsed.bozo and not parsed.entries:
            continue

        for entry in reversed(parsed.entries):
            link = entry.get("link")
            if not link or link in posted_links:
                continue

            title = clean_html(entry.get("title", "بدون عنوان"))
            summary = clean_html(entry.get("summary", ""))
            category = find_category(title, summary)

            if category is None:
                posted_links.add(link)  # نامرتبط، دیگر بررسی نشود
                continue

            title_fa = translate_to_persian(title)
            summary_fa = translate_to_persian(summary)
            return link, title_fa, summary_fa, category

    return None


def main():
    if "اینجا" in BOT_TOKEN:
        log.error("BOT_TOKEN تنظیم نشده.")
        return
    if "یوزرنیم_کانال_شما" in CHANNEL_ID:
        log.error("CHANNEL_ID تنظیم نشده.")
        return

    log.info(f"شروع اجرای مداوم (حداکثر {MAX_RUN_SECONDS} ثانیه)...")
    posted_links = load_posted_links()
    last_post_time = load_last_post_time()
    run_start = time.time()
    loop_count = 0

    while time.time() - run_start < MAX_RUN_SECONDS:
        loop_count += 1
        now = time.time()

        if now - last_post_time >= MIN_SECONDS_BETWEEN_POSTS:
            candidate = find_next_candidate(posted_links)
            if candidate:
                link, title, summary, category = candidate
                message = format_message(title, summary, category)
                if send_to_channel(message):
                    log.info(f"پست شد [{category}]: {title[:60]}")
                    posted_links.add(link)
                    last_post_time = time.time()
                    save_posted_links(posted_links)
                    save_last_post_time(last_post_time)
                    git_push_state()
                else:
                    log.warning(f"پست نشد: {link}")
            else:
                log.info("خبر جدید مرتبطی پیدا نشد.")
        else:
            remaining = int(MIN_SECONDS_BETWEEN_POSTS - (now - last_post_time))
            log.info(f"در حال استراحت تا پست بعدی ({remaining} ثانیه مانده)...")

        # هر ۲۰ دور، وضعیت را ذخیره کن حتی اگر پستی انجام نشده باشد
        if loop_count % 20 == 0:
            save_posted_links(posted_links)
            git_push_state()

        time.sleep(CHECK_INTERVAL_SECONDS)

    log.info("زمان این اجرا تمام شد؛ وضعیت نهایی ذخیره می‌شود.")
    save_posted_links(posted_links)
    save_last_post_time(last_post_time)
    git_push_state()


if __name__ == "__main__":
    main()
