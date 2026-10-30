import threading
import asyncio
import hashlib
import hmac
import io
import json
import os
import random
import re
import time
import datetime
from urllib.parse import quote
import requests
import telebot
from telebot import types
from telethon import TelegramClient, events
from telethon.sessions import StringSession

# ===================== CONFIG (TESTING VALUES) =====================
API_ID = int(os.environ.get('API_ID', ''))
API_HASH = os.environ.get('API_HASH', '')
SESSION_STR = os.environ.get('SESSION_STR', '')
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
OWNER_ID = int(os.environ.get('OWNER_ID', ''))

# Target Bot
TARGET_BOT = os.environ.get('TARGET_BOT', '@Doubtbustbot')

# Branding
BRAND = "@ModAppsKing"
MAIN_BOT_NAME = "@Faphouse_King_Bot"

# Custom Links
TERAPLAY_LINK = "https://play.google.com/store/apps/details?id=in.shadowlink.anyplay"
PLAN_LINK = "https://t.me/R0Y4L_KING"
PORT = int(os.environ.get('PORT', '8080'))

# Delivered video kitni der baad delete ho (seconds). 0 = kabhi delete nahi.
AUTO_DELETE_SECONDS = int(os.environ.get('AUTO_DELETE_SECONDS', '3600'))

# Video ka cover (poster image) — target bot ki branding hatane ke liye.
# Koi bhi public JPEG URL chalega; default hamara repo wala cover hai.
REPLACE_COVER = os.environ.get('REPLACE_COVER', '1') == '1'
COVER_URL = os.environ.get(
    'COVER_URL',
    'https://raw.githubusercontent.com/R0Y4L-KING/Useless/main/cover.jpg',
)

# ---- Premium / payment (UPI only, koi crypto nahi) ----
UPI_ID = os.environ.get('UPI_ID', '20213904@axl')
UPI_NAME = os.environ.get('UPI_NAME', 'ModAppsKing')
SUPPORT_LINK = os.environ.get('SUPPORT_LINK', 'https://t.me/R0Y4L_KING')

# Free users ke liye rozana download limit. 0 = unlimited (koi rok nahi)
FREE_DAILY_LIMIT = int(os.environ.get('FREE_DAILY_LIMIT', '0'))

# ---- Ads verification (shortener) ----
# API key Render ke env me daalo: SHORTENER_API_KEY
SHORTENER_ENDPOINT = os.environ.get('SHORTENER_ENDPOINT', 'https://vipshort.in/api')
SHORTENER_API_KEY = os.environ.get('SHORTENER_API_KEY', '')
FREE_TRIAL_DOWNLOADS = int(os.environ.get('FREE_TRIAL_DOWNLOADS', '3'))
ADS_REWARD_DOWNLOADS = int(os.environ.get('ADS_REWARD_DOWNLOADS', '5'))
VERIFY_TOKEN_TTL_MIN = int(os.environ.get('VERIFY_TOKEN_TTL_MIN', '60'))

# Premium data: MongoDB (recommended) ya local JSON file
MONGODB_URI = os.environ.get('MONGODB_URI', '')
DB_PATH = os.environ.get('DB_PATH', 'premium_db.json')

# UPI payment page (hosted QR page)
PAYMENT_PAGE_URL = os.environ.get(
    'PAYMENT_PAGE_URL', 'https://r0y4l-king.github.io/upi-pay/'
)


def payment_page_url(amount=None):
    """UPI page ka link — amount diya to query me bhi jaayega (page auto-fill karta hai)."""
    if not amount:
        return PAYMENT_PAGE_URL
    sep = "&" if "?" in PAYMENT_PAGE_URL else "?"
    return f"{PAYMENT_PAGE_URL}{sep}pa={quote(UPI_ID)}&am={int(amount)}&pn={quote(UPI_NAME)}"
PREMIUM_BANNER_URL = os.environ.get(
    'PREMIUM_BANNER_URL',
    'https://raw.githubusercontent.com/R0Y4L-KING/Useless/main/premium_banner.jpg',
)
# 'Scan to Pay' wala QR image
SCAN_QR_URL = os.environ.get(
    'SCAN_QR_URL',
    'https://raw.githubusercontent.com/R0Y4L-KING/save-restricted-bot/main/assets/upi_qr.png',
)

LIFETIME_DAYS = 36500

PLANS = {
    "p50": {"price": 50, "days": 30, "label": "1 Month — ₹50"},
    "p120": {"price": 120, "days": 90, "label": "3 Months — ₹120 (Save 20%)"},
    "p200": {"price": 200, "days": LIFETIME_DAYS, "label": "Lifetime — ₹200"},
}


def _validity_text(days):
    days = int(days)
    if days >= LIFETIME_DAYS:
        return "Lifetime"
    if days >= 30 and days % 30 == 0:
        months = days // 30
        return "1 Month" if months == 1 else f"{months} Months"
    return f"{days} days"


def _expiry_text(until, days):
    if int(days) >= LIFETIME_DAYS:
        return "Lifetime access — kabhi expire nahi hoga"
    return f"{until.strftime('%d %b %Y, %I:%M %p')} (UTC) tak"


def _plan_line(until):
    if until is None:
        return "🆓 Free"
    if (until - _now()).days > 3650:
        return "💎 Premium (Lifetime)"
    return f"💎 Premium ({until.strftime('%d %b %Y')} tak)"

# ---- Razorpay (auto payment detection) ----
# Dono keys set hain to payment AUTOMATIC verify hota hai (webhook + polling).
# Keys nahi hain to bot purane manual flow (UPI QR + UTR approval) pe chalta hai.
RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', '')
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', '')
RAZORPAY_WEBHOOK_SECRET = os.environ.get('RAZORPAY_WEBHOOK_SECRET', '')
AUTO_VERIFY = bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)
RAZORPAY_API = "https://api.razorpay.com/v1"
# Order kitni der tak poll kare (20 sec interval)
PAYMENT_WATCH_MINUTES = int(os.environ.get('PAYMENT_WATCH_MINUTES', '20'))
# ===================================================================

bot = telebot.TeleBot(BOT_TOKEN)

try:
    MAIN_BOT_USERNAME = f"@{bot.get_me().username}"
    print(f"Bot Username detected as: {MAIN_BOT_USERNAME}")
except Exception as e:
    print(f"Error fetching bot username: {e}")
    MAIN_BOT_USERNAME = os.environ.get('BOT_USERNAME', '') or "@YourBotUsername"

loop = asyncio.new_event_loop()
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH, loop=loop)

processing_lock = threading.Lock()
user_requests = {}

# ================= LOADING ANIMATION (spinner) =================
# Ping-pong progress bar — message edit karke animate hoti hai
BAR_FRAMES = [
    "▰▱▱▱▱▱▱▱",
    "▰▰▱▱▱▱▱▱",
    "▰▰▰▱▱▱▱▱",
    "▰▰▰▰▱▱▱▱",
    "▰▰▰▰▰▱▱▱",
    "▰▰▰▰▰▰▱▱",
    "▰▰▰▰▰▰▰▱",
    "▰▰▰▰▰▰▰▰",
    "▱▰▰▰▰▰▰▰",
    "▱▱▰▰▰▰▰▰",
    "▱▱▱▰▰▰▰▰",
    "▱▱▱▱▰▰▰▰",
    "▱▱▱▱▱▰▰▰",
    "▱▱▱▱▱▱▰▰",
    "▱▱▱▱▱▱▱▰",
]

SPINNER_TEXT = (
    "⏳ **Video connect ho rahi hai...**\n\n"
    "`{bar}`\n\n"
    "💎 **Premium lo — no waiting, instant downloads!**"
)

_spinners = {}
_spinners_lock = threading.Lock()


def start_spinner(chat_id, message_id, interval=1.6):
    """Message ko continuously animate karta hai jab tak stop na ho."""
    stop_event = threading.Event()
    key = (chat_id, message_id)

    with _spinners_lock:
        old = _spinners.get(key)
        if old:
            old.set()
        _spinners[key] = stop_event

    def animate():
        i = 0
        while not stop_event.is_set():
            try:
                bot.edit_message_text(
                    SPINNER_TEXT.format(bar=BAR_FRAMES[i % len(BAR_FRAMES)]),
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode="Markdown",
                )
            except Exception:
                pass
            i += 1
            stop_event.wait(interval)
        with _spinners_lock:
            if _spinners.get(key) is stop_event:
                _spinners.pop(key, None)

    threading.Thread(target=animate, daemon=True).start()


def stop_spinner(chat_id, message_id):
    with _spinners_lock:
        ev = _spinners.pop((chat_id, message_id), None)
    if ev:
        ev.set()


def _edit(chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
    """Spinner rok kar message edit karta hai (ek hi jagah se saare updates)."""
    stop_spinner(chat_id, message_id)
    try:
        bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except Exception as e:
        print(f"[edit] {e}")


# ================= CAPTION HELPERS =================
def _human_size(num):
    if not num:
        return None
    num = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024 or unit == "TB":
            return f"{int(num)} B" if unit == "B" else f"{num:.2f} {unit}"
        num /= 1024.0


def _human_duration(seconds):
    if not seconds:
        return None
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h and m == 0 and s == 0:
        return "1 hour" if h == 1 else f"{h} hours"
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def build_video_caption(sent):
    size = dur = None
    if getattr(sent, "video", None):
        size = getattr(sent.video, "file_size", None)
        dur = getattr(sent.video, "duration", None)
    elif getattr(sent, "document", None):
        size = getattr(sent.document, "file_size", None)
        dur = getattr(sent.document, "duration", None)

    lines = []
    size_txt = _human_size(size)
    if size_txt:
        lines.append(f"⚖️ Size: {size_txt}")
    dur_txt = _human_duration(dur)
    if dur_txt:
        lines.append(f"⏳ Duration: {dur_txt}")
    if lines:
        lines.append("")

    if AUTO_DELETE_SECONDS > 0:
        lines.append(
            f"⚠️ Note: This video will be auto-deleted from this chat in "
            f"{_human_duration(AUTO_DELETE_SECONDS)}"
        )
        lines.append("")

    lines.append(f"Thanks for using {MAIN_BOT_NAME} ❤️")
    return "\n".join(lines)


def schedule_auto_delete(chat_id, message_id, delay):
    """Delete job DB me queue karo. Sweeper thread ise utha lega —
    process restart / Render sleep ke baad bhi delete hona bacha rahega."""
    if delay <= 0:
        return
    key = f"{chat_id}:{message_id}"
    store.add_deletion(key, {
        "key": key,
        "chat_id": chat_id,
        "message_id": message_id,
        "delete_at": (_now() + datetime.timedelta(seconds=int(delay))).isoformat(),
    })
    print(f"[auto-delete] queued {key} (+{delay}s)")


# ================= TELETHON SIDE (Userbot Relay) =================

async def _send_start_to_target():
    try:
        await client.send_message(TARGET_BOT, "/start")
        print("[telethon] Target bot ko /start bhej diya gaya hai! ✅")
    except Exception as e:
        pass

async def _fetch_from_target(url, user_chat_id, call_msg_id):
    target_entity = await client.get_entity(TARGET_BOT)
    main_bot_entity = await client.get_entity(MAIN_BOT_USERNAME)
    
    await client.send_message(target_entity, "/start")
    await asyncio.sleep(1.5) 
    
    await client.send_message(target_entity, url)
    print(f"[telethon] Link sent to target bot for user {user_chat_id}")
    
    forwarded_video_ids = set()
    ad_clicked = False
    quality_clicked = False
    last_progress_text = ""
    
    # 🧠 SUPER LOOP (120 * 2 sec = 240 seconds = 4 minutes)
    for _ in range(120): 
        await asyncio.sleep(2)  # Fast check
        history = await client.get_messages(target_entity, limit=4)
        
        for msg in history:
            if msg.out: 
                continue 
            
            # ---> CASE A: Target bot ne ERROR de diya <---
            if msg.text and "ek link fir se bhejo" in msg.text.lower():
                print("[telethon] Target bot fail ho gaya (Error message mila).")
                _edit(
                    user_chat_id,
                    call_msg_id,
                    "❌ **Download Failed!**\n\nTarget server par issue hai. Kripya koi dusra link try karein.",
                )
                return False

            # ---> CASE B: PROGRESS BAR MIRRORING <---
            if msg.text and ("Progress" in msg.text or "Speed:" in msg.text or "ETA:" in msg.text):
                progress_text = msg.text
                if progress_text != last_progress_text:
                    plan_markup = types.InlineKeyboardMarkup()
                    plan_markup.add(types.InlineKeyboardButton("💎 Buy Premium", callback_data="premium_menu"))
                    _edit(
                        user_chat_id,
                        call_msg_id,
                        f"{progress_text}\n\n⚡ Multiple videos ek saath download karna hai?\nPremium le lo!",
                        reply_markup=plan_markup,
                    )
                    last_progress_text = progress_text
                continue # Agar progress bar hai, to aage button check karne ki zarurat nahi

            # ---> CASE C: Video Aagayi <---
            if msg.video or msg.document:
                if msg.id not in forwarded_video_ids:
                    print("[telethon] Video aagayi! Forward kar raha hu...")
                    forwarded_video_ids.add(msg.id)
                    
                    forwarded_msg = await client.forward_messages(main_bot_entity, msg)
                    await asyncio.sleep(3) 
                    
                    await client.send_message(
                        main_bot_entity, 
                        f"DELIVER {user_chat_id}",
                        reply_to=forwarded_msg.id
                    )
                    
                    _edit(
                        user_chat_id,
                        call_msg_id,
                        "✅ **Video Uploading Finished!**",
                    )
                    return True

            # ---> CASE D: Menu Buttons Aaye <---
            if msg.buttons:
                menu_type = None
                
                # Check karo ki ye kaunsa menu hai
                for row in msg.buttons:
                    for btn in row:
                        btn_txt = btn.text.lower()
                        if "download" in btn_txt or "telegram" in btn_txt:
                            menu_type = "ad"
                        elif "1080" in btn_txt or "720" in btn_txt or "480" in btn_txt or "auto" in btn_txt:
                            menu_type = "quality"

                # 1. Agar Ad Menu hai aur click nahi hua
                if menu_type == "ad" and not ad_clicked:
                    clicked = False
                    for i, row in enumerate(msg.buttons):
                        for j, btn in enumerate(row):
                            if "download" in btn.text.lower() or "telegram" in btn.text.lower():
                                try:
                                    print(f"[telethon] Clicking Ad Menu: {btn.text}")
                                    await msg.click(i, j) # msg.click(i, j) 100% kaam karta hai
                                    ad_clicked = True
                                    clicked = True
                                except Exception as e:
                                    print(f"Ad click error: {e}")
                                break
                        if clicked: break

                # 2. Agar Quality Menu hai aur click nahi hua
                elif menu_type == "quality" and not quality_clicked:
                    clicked = False
                    for target_quality in ["1080", "720", "480", "240", "auto", "best"]:
                        for i, row in enumerate(msg.buttons):
                            for j, btn in enumerate(row):
                                if target_quality in btn.text.lower():
                                    try:
                                        print(f"[telethon] Clicking Quality: {btn.text}")
                                        await msg.click(i, j)
                                        quality_clicked = True
                                        clicked = True

                                        _edit(
                                            user_chat_id,
                                            call_msg_id,
                                            "⏳ **Video server par connect ho rahi hai...**",
                                        )
                                    except Exception as e:
                                        print(f"Quality click error: {e}")
                                    break
                            if clicked: break
                        if clicked: break
                
    print("[telethon] Error: Video aane me timeout ho gaya.")
    _edit(
        user_chat_id,
        call_msg_id,
        "❌ **Timeout Error**\n\nVideo download hone me bohot zyada time lag gaya. Please try again later.",
    )
    return False

def start_telethon_thread():
    asyncio.set_event_loop(loop)
    loop.run_until_complete(client.connect())
    print("Userbot Session Active...") 
    loop.run_forever()

threading.Thread(target=start_telethon_thread, daemon=True).start()
# ====================================================


# ================= PREMIUM STORE + PAYMENT (UPI) =================
try:
    from pymongo import MongoClient
except Exception:
    MongoClient = None


def _now():
    return datetime.datetime.utcnow()


class Store:
    """Premium users + orders. MONGODB_URI ho to Mongo, warna local JSON."""

    def __init__(self, mongo_uri, json_path):
        self._lock = threading.Lock()
        self._users = None
        self._orders = None
        self._deletions = None
        self._tokens = None
        self._path = json_path
        self._data = {"users": {}, "orders": {}, "deletions": {}, "tokens": {}}

        if mongo_uri and MongoClient:
            try:
                client = MongoClient(mongo_uri, serverSelectionTimeoutMS=8000)
                client.admin.command("ping")
                try:
                    db = client.get_default_database()
                except Exception:
                    db = client["faphouse"]
                self._users = db["users"]
                self._orders = db["orders"]
                self._deletions = db["deletions"]
                self._tokens = db["verify_tokens"]
                print("[store] MongoDB connected")
                return
            except Exception as e:
                print(f"[store] Mongo connect fail ({e}) — local JSON use hoga")

        self._load()
        print(f"[store] local JSON store: {self._path}")

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r") as f:
                    self._data = json.load(f)
            except Exception as e:
                print(f"[store] load fail: {e}")

    def _save(self):
        if self._users is not None:
            return
        tmp = self._path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f)
        os.replace(tmp, self._path)

    def get_user(self, user_id):
        uid = str(user_id)
        if self._users is not None:
            doc = self._users.find_one({"_id": uid}) or {}
            doc.pop("_id", None)
            return doc
        with self._lock:
            return dict(self._data["users"].get(uid, {}))

    def update_user(self, user_id, **fields):
        uid = str(user_id)
        if self._users is not None:
            self._users.update_one({"_id": uid}, {"$set": fields}, upsert=True)
            return
        with self._lock:
            self._data["users"].setdefault(uid, {}).update(fields)
            self._save()

    def save_order(self, order_id, order):
        if self._orders is not None:
            self._orders.update_one({"_id": str(order_id)}, {"$set": order}, upsert=True)
            return
        with self._lock:
            self._data["orders"].setdefault(str(order_id), {}).update(order)
            self._save()

    def get_order(self, order_id):
        if self._orders is not None:
            doc = self._orders.find_one({"_id": str(order_id)}) or {}
            doc.pop("_id", None)
            return doc
        with self._lock:
            return dict(self._data["orders"].get(str(order_id), {}))

    def set_order_status(self, order_id, status):
        self.save_order(order_id, {"status": status})

    # ---- auto-delete queue ----
    def add_deletion(self, key, doc):
        if self._deletions is not None:
            self._deletions.update_one({"_id": key}, {"$set": doc}, upsert=True)
            return
        with self._lock:
            self._data.setdefault("deletions", {})[key] = doc
            self._save()

    def due_deletions(self, now_iso):
        docs = []
        if self._deletions is not None:
            for doc in self._deletions.find({"delete_at": {"$lte": now_iso}}):
                doc.pop("_id", None)
                docs.append(doc)
            return docs
        with self._lock:
            for doc in self._data.get("deletions", {}).values():
                if str(doc.get("delete_at", "")) <= now_iso:
                    docs.append(dict(doc))
        return docs

    def remove_deletion(self, key):
        if self._deletions is not None:
            self._deletions.delete_one({"_id": key})
            return
        with self._lock:
            self._data.setdefault("deletions", {}).pop(key, None)
            self._save()

    # ---- ad verification tokens ----
    def add_token(self, token, doc):
        if self._tokens is not None:
            self._tokens.update_one({"_id": token}, {"$set": doc}, upsert=True)
            return
        with self._lock:
            self._data.setdefault("tokens", {})[token] = doc
            self._save()

    def get_token(self, token):
        if self._tokens is not None:
            doc = self._tokens.find_one({"_id": token}) or {}
            doc.pop("_id", None)
            return doc
        with self._lock:
            return dict(self._data.get("tokens", {}).get(token, {}))

    def use_token(self, token):
        if self._tokens is not None:
            self._tokens.update_one({"_id": token}, {"$set": {"used": True, "used_at": _now().isoformat()}})
            return
        with self._lock:
            doc = self._data.setdefault("tokens", {}).get(token)
            if doc:
                doc["used"] = True
                doc["used_at"] = _now().isoformat()
                self._save()


store = Store(MONGODB_URI, DB_PATH)


def _deletion_sweeper():
    """Har 60 second me due deletions delete karta hai."""
    while True:
        try:
            now_iso = _now().isoformat()
            for doc in store.due_deletions(now_iso):
                key = doc.get("key") or f"{doc.get('chat_id')}:{doc.get('message_id')}"
                try:
                    bot.delete_message(doc["chat_id"], doc["message_id"])
                    print(f"[auto-delete] deleted {key}")
                except Exception as e:
                    print(f"[auto-delete] {key} delete fail: {e}")
                store.remove_deletion(key)
        except Exception as e:
            print(f"[auto-delete] sweep error: {e}")
        time.sleep(60)


threading.Thread(target=_deletion_sweeper, daemon=True).start()
awaiting_utr = {}


def premium_until(user_id):
    """Active premium expiry (datetime) ya None."""
    exp = store.get_user(user_id).get("premium_until")
    if not exp:
        return None
    try:
        until = datetime.datetime.fromisoformat(str(exp))
    except Exception:
        return None
    return until if until > _now() else None


def is_premium(user_id):
    return premium_until(user_id) is not None


def grant_premium(user_id, days):
    base = premium_until(user_id) or _now()
    until = base + datetime.timedelta(days=int(days))
    store.update_user(user_id, premium_until=until.isoformat())
    return until


def revoke_premium(user_id):
    store.update_user(user_id, premium_until=None)


def _today():
    return _now().strftime("%Y-%m-%d")


def usage_today(user_id):
    user = store.get_user(user_id)
    if user.get("usage_date") != _today():
        return 0
    return int(user.get("usage_count", 0))


def bump_usage(user_id):
    user = store.get_user(user_id)
    store.update_user(
        user_id,
        usage_date=_today(),
        usage_count=usage_today(user_id) + 1,
        total_downloads=int(user.get("total_downloads", 0)) + 1,
    )


def consume_download(user_id):
    """Ek download consume karo. Returns (allowed, info).
    info: 'premium' | 'credits' | 'free' | 'verify' | 'daily'
    """
    if is_premium(user_id):
        bump_usage(user_id)
        return True, "premium"

    if FREE_DAILY_LIMIT > 0 and usage_today(user_id) >= FREE_DAILY_LIMIT:
        return False, "daily"

    user = store.get_user(user_id)
    credits = int(user.get("credits", 0))
    if credits > 0:
        store.update_user(user_id, credits=credits - 1)
        bump_usage(user_id)
        return True, "credits"

    free_used = int(user.get("free_used", 0))
    if free_used < FREE_TRIAL_DOWNLOADS:
        store.update_user(user_id, free_used=free_used + 1)
        bump_usage(user_id)
        return True, "free"

    return False, "verify"


def downloads_left_text(user_id):
    if is_premium(user_id):
        return "Unlimited (Premium)"
    user = store.get_user(user_id)
    credits = int(user.get("credits", 0))
    free_used = int(user.get("free_used", 0))
    free_left = max(0, FREE_TRIAL_DOWNLOADS - free_used)
    if credits > 0:
        return f"{credits} (ad-verified) + {free_left} free"
    return f"{free_left} free"


# ---------- Ads verification (shortlink) ----------
def make_short_link(dest_url, alias=None):
    """Shortener se chhota link banao. Fail ho to None."""
    if not SHORTENER_API_KEY:
        print("[ads] SHORTENER_API_KEY set nahi hai — seedha link use hoga")
        return None

    params = {"api": SHORTENER_API_KEY, "url": dest_url}
    if alias:
        params["alias"] = alias

    try:
        r = requests.get(SHORTENER_ENDPOINT, params=params, timeout=20)
        r.raise_for_status()
        text = (r.text or "").strip()
        if text.startswith("http"):
            return text
        try:
            data = r.json()
        except Exception:
            data = {}
        for key in ("shortenedUrl", "shorturl", "short_url", "url", "link"):
            if data.get(key):
                return data[key]
        print(f"[ads] shortener response samajh nahi aaya: {text[:200]}")
    except Exception as e:
        print(f"[ads] shortener fail: {e}")
    return None


def create_verify_link(user_id):
    """Ad verification ka link banao (Telegram deep-link ko shorten karke)."""
    token = "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=10))
    store.add_token(token, {
        "token": token,
        "user_id": int(user_id),
        "created": _now().isoformat(),
        "used": False,
    })
    bot_username = MAIN_BOT_USERNAME.lstrip("@")
    dest = f"https://t.me/{bot_username}?start=verify_{token}"
    short = make_short_link(dest, alias=None)
    if short:
        print(f"[ads] verify link for {user_id}: {short}")
        return short, token
    return dest, token


def handle_verify_payload(message, token):
    """Ads dekhne ke baad user /start verify_<token> se aata hai."""
    chat_id = message.chat.id
    user_id = message.from_user.id
    doc = store.get_token(token)

    if not doc:
        bot.send_message(
            chat_id,
            "❌ Ye verification link valid nahi hai. /verify se naya link banao.",
        )
        return

    if doc.get("used"):
        bot.send_message(
            chat_id, "❌ Ye link pehle use ho chuka hai. /verify se naya link banao."
        )
        return

    if int(doc.get("user_id", 0)) != user_id:
        bot.send_message(
            chat_id, "❌ Ye link kisi aur user ka hai. /verify se apna link banao."
        )
        return

    try:
        created = datetime.datetime.fromisoformat(str(doc.get("created")))
    except Exception:
        created = _now()
    if (_now() - created) > datetime.timedelta(minutes=VERIFY_TOKEN_TTL_MIN):
        bot.send_message(
            chat_id, "⌛ Ye link expire ho gaya. /verify se naya link banao."
        )
        return

    store.use_token(token)
    user = store.get_user(user_id)
    new_credits = int(user.get("credits", 0)) + ADS_REWARD_DOWNLOADS
    store.update_user(user_id, credits=new_credits)

    bot.send_message(
        chat_id,
        "✅ **Verification complete!**\n\n"
        f"🎁 Aapko {ADS_REWARD_DOWNLOADS} downloads mil gaye.\n"
        f"📥 Ab aapke paas total **{new_credits}** ad-verified downloads hain.\n\n"
        "Ab apna Faphouse link bhejo! 🚀",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown",
    )


@bot.message_handler(commands=['verify'])
def verify_command(message):
    user_id = message.from_user.id
    if is_premium(user_id):
        bot.send_message(
            message.chat.id, "💎 Aap Premium user ho — unlimited downloads, koi ads nahi!"
        )
        return
    link, _ = create_verify_link(user_id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🔓 Verify Now (Ads)", url=link))
    bot.send_message(
        message.chat.id,
        f"🔓 **Ad Verification**\n\n"
        f"Link kholo, ads complete karo, phir {ADS_REWARD_DOWNLOADS} downloads milenge.",
        reply_markup=markup,
        parse_mode="Markdown",
    )


def upi_qr(amount, note):
    """UPI intent ka QR (PNG BytesIO) — amount pre-filled."""
    import qrcode

    upi_url = (
        f"upi://pay?pa={quote(UPI_ID)}&pn={quote(UPI_NAME)}"
        f"&am={amount}&cu=INR&tn={quote(note)}"
    )
    qr = qrcode.QRCode(box_size=10, border=3)
    qr.add_data(upi_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ---------- Razorpay helpers (auto verification) ----------
def _rzp_auth():
    return (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)


def rzp_create_order(receipt, amount_paise, notes):
    r = requests.post(
        f"{RAZORPAY_API}/orders",
        auth=_rzp_auth(),
        json={
            "amount": int(amount_paise),
            "currency": "INR",
            "receipt": str(receipt),
            "notes": notes,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def rzp_create_qr(receipt, amount_paise, description, notes):
    r = requests.post(
        f"{RAZORPAY_API}/payments/qr_codes",
        auth=_rzp_auth(),
        json={
            "type": "upi_qr",
            "name": UPI_NAME,
            "usage": "single_use",
            "fixed_amount": True,
            "payment_amount": int(amount_paise),
            "description": description,
            "notes": notes,
            "close_by": int(time.time()) + 3600,
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def rzp_order_status(rzp_order_id):
    r = requests.get(
        f"{RAZORPAY_API}/orders/{rzp_order_id}", auth=_rzp_auth(), timeout=20
    )
    r.raise_for_status()
    return r.json()


def rzp_qr_payments(qr_id):
    r = requests.get(
        f"{RAZORPAY_API}/payments/qr_codes/{qr_id}/payments",
        auth=_rzp_auth(),
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def _rzp_order_paid(order):
    """Gateway se poochho ki paisa aaya ya nahi."""
    if not AUTO_VERIFY:
        return False

    rzp_id = order.get("rzp_order_id")
    if rzp_id:
        try:
            if rzp_order_status(rzp_id).get("status") == "paid":
                return True
        except Exception as e:
            print(f"[rzp] order status fail: {e}")

    qr_id = order.get("qr_id")
    if qr_id:
        try:
            items = (rzp_qr_payments(qr_id) or {}).get("items") or []
            if items:
                return True
        except Exception as e:
            print(f"[rzp] qr payments fail: {e}")

    return False


def activate_order(order_id, source="auto"):
    """Payment confirm — premium activate + user ko batao. Idempotent."""
    order = store.get_order(order_id)
    if not order:
        print(f"[premium] activate: order {order_id} nahi mila")
        return False
    if order.get("status") == "approved":
        return False
    if order.get("status") == "cancelled":
        print(f"[premium] activate: order {order_id} cancelled tha, skip")
        return False

    user_id = order.get("user_id")
    until = grant_premium(user_id, int(order.get("days", 0)))
    store.save_order(order_id, {
        "status": "approved",
        "approved_at": _now().isoformat(),
        "source": source,
    })
    print(f"[premium] order {order_id} approved via {source} -> user {user_id}")

    try:
        bot.send_message(
            user_id,
            "✅ **Payment detected!**\n\n"
            f"💎 Premium: {_expiry_text(until, order.get('days', 0))}\n"
            f"🧾 Order: {order_id}\n\n"
            "Ab unlimited downloads — enjoy! 🚀",
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"[premium] user notify fail: {e}")
    return True


def watch_payment(order_id):
    """Background me payment check karta rehta hai (webhook na aaye to bhi)."""
    def run():
        rounds = max(1, (PAYMENT_WATCH_MINUTES * 60) // 20)
        for _ in range(rounds):
            time.sleep(20)
            order = store.get_order(order_id)
            if not order or order.get("status") in ("approved", "cancelled"):
                return
            if _rzp_order_paid(order):
                activate_order(order_id, source="poll")
                return
        print(f"[rzp] order {order_id} watch timeout")

    threading.Thread(target=run, daemon=True).start()


def _verify_webhook(body, signature):
    if not RAZORPAY_WEBHOOK_SECRET:
        print("[webhook] RAZORPAY_WEBHOOK_SECRET set nahi hai — request reject")
        return False
    expected = hmac.new(
        RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def _handle_rzp_event(payload):
    event = payload.get("event", "")
    if event not in ("payment.captured", "order.paid", "qr_code.credited"):
        print(f"[webhook] ignore event: {event}")
        return

    entities = payload.get("payload") or {}
    notes = {}
    for key in ("payment", "order", "qr_code"):
        entity = ((entities.get(key) or {}).get("entity") or {})
        if entity.get("notes"):
            notes = entity["notes"]
            break

    order_id = str(notes.get("order_id") or "")
    if not order_id:
        print("[webhook] notes me order_id nahi mila")
        return

    print(f"[webhook] {event} -> order {order_id}")
    activate_order(order_id, source=f"webhook:{event}")


def plans_markup():
    markup = types.InlineKeyboardMarkup(row_width=1)
    for key, plan in PLANS.items():
        markup.add(types.InlineKeyboardButton(plan["label"], callback_data=f"plan:{key}"))
    markup.add(types.InlineKeyboardButton("🌐 Pay Now (UPI)", url=payment_page_url()))
    markup.add(types.InlineKeyboardButton("📲 Scan to Pay", callback_data="scanqr"))
    markup.add(types.InlineKeyboardButton("⬅️ Back to Home", callback_data="back_home"))
    return markup


def premium_text():
    return (
        "💎 **Premium Membership Plans**\n\n"
        "• 1 Month: ₹50\n"
        "• 3 Months: ₹120 (Save 20%)\n"
        "• Lifetime: ₹200 (One-Time)\n\n"
        "🏦 **UPI ID:** " + UPI_ID + "\n"
        "📲 Scan to Pay ya 🌐 Pay Now (UPI) dabao\n"
        "📤 Payment ke baad 'Send Payment Proof' bhejo"
    )


def send_plans(chat_id):
    sent_photo = False
    if PREMIUM_BANNER_URL:
        try:
            bot.send_photo(
                chat_id,
                PREMIUM_BANNER_URL,
                caption=premium_text(),
                reply_markup=plans_markup(),
                parse_mode="Markdown",
            )
            sent_photo = True
        except Exception as e:
            print(f"[premium] banner fail: {e}")
    if not sent_photo:
        bot.send_message(
            chat_id,
            premium_text(),
            reply_markup=plans_markup(),
            parse_mode="Markdown",
        )


@bot.message_handler(commands=['premium', 'plans', 'buy'])
def premium_command(message):
    send_plans(message.chat.id)


@bot.message_handler(func=lambda msg: msg.text == "💎 Premium")
def premium_button(message):
    send_plans(message.chat.id)


@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    user_requests.pop(message.chat.id, None)
    awaiting_utr.pop(message.from_user.id, None)
    bot.send_message(message.chat.id, "✅ Sab reset ho gaya. Naya link bhej do.")


@bot.callback_query_handler(func=lambda call: call.data == "premium_menu")
def cb_premium_menu(call):
    bot.answer_callback_query(call.id)
    send_plans(call.message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data == "premium_cancel")
def cb_premium_cancel(call):
    awaiting_utr.pop(call.from_user.id, None)
    bot.answer_callback_query(call.id, "Cancel ho gaya.")
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("plan:"))
def cb_plan(call):
    key = call.data.split(":", 1)[1]
    plan = PLANS.get(key)
    if not plan:
        bot.answer_callback_query(call.id, "Plan nahi mila, /premium dobara bhejo.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    start_payment(call.message.chat.id, call.from_user.id, key)


@bot.callback_query_handler(func=lambda call: call.data == "back_home")
def cb_back_home(call):
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "🏠 **Home**\n\n"
        "📥 Apna Faphouse link bhejo, baaki mera kaam!\n"
        "💎 Premium ke liye /premium bhejo.",
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown",
    )


def start_payment(chat_id, user_id, key):
    """Order banao aur payment screen bhejo (auto gateway ya manual UPI)."""
    plan = PLANS.get(key)
    if not plan:
        bot.send_message(chat_id, "Plan nahi mila. /premium dobara bhejo.")
        return

    order_id = str(random.randint(10000000, 99999999))
    store.save_order(order_id, {
        "user_id": user_id,
        "plan": key,
        "price": plan["price"],
        "days": plan["days"],
        "status": "pending",
        "created": _now().isoformat(),
    })

    notes = {
        "order_id": order_id,
        "user_id": str(user_id),
        "days": str(plan["days"]),
    }

    # ---- Auto mode: gateway QR banao, payment khud detect hoga ----
    if AUTO_VERIFY:
        try:
            rzp_order = rzp_create_order(order_id, plan["price"] * 100, notes)
            qr = rzp_create_qr(
                order_id, plan["price"] * 100, f"Premium {order_id}", notes
            )
            store.save_order(order_id, {
                "rzp_order_id": rzp_order.get("id"),
                "qr_id": qr.get("id"),
                "qr_image": qr.get("image_url"),
            })

            caption = (
                "💎 **Premium Subscription Payment**\n\n"
                f"💰 Amount: ₹{plan['price']}\n"
                f"📅 Validity: {_validity_text(plan['days'])}\n"
                f"🧾 Order ID: {order_id}\n\n"
                "**Payment Instructions:**\n"
                "1️⃣ Neeche wala QR kisi bhi UPI app se scan karo\n"
                f"2️⃣ Exactly ₹{plan['price']} pay karo\n"
                "3️⃣ Payment **automatically detect** ho jaayegi\n\n"
                "⚡ Premium khud activate ho jaayega — screenshot bhejne ki zarurat nahi."
            )
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton(
                "🔄 Check Payment", callback_data=f"checkpay:{order_id}"))
            markup.add(types.InlineKeyboardButton(
                "❌ CANCEL ORDER", callback_data=f"cancelorder:{order_id}"))

            image = qr.get("image_url")
            if image:
                bot.send_photo(
                    chat_id, image,
                    caption=caption, reply_markup=markup, parse_mode="Markdown",
                )
            else:
                bot.send_photo(
                    chat_id,
                    upi_qr(plan["price"], f"Premium {order_id}"),
                    caption=caption, reply_markup=markup, parse_mode="Markdown",
                )

            watch_payment(order_id)
            return
        except Exception as e:
            print(f"[rzp] auto order fail: {e} — manual flow pe fallback")

    # ---- Manual fallback (gateway keys nahi hain ya API fail hui) ----
    caption = (
        "💎 **Premium Subscription Payment**\n\n"
        f"💰 Amount: ₹{plan['price']}\n"
        f"📅 Validity: {_validity_text(plan['days'])}\n"
        f"🧾 Order ID: {order_id}\n"
        f"🏦 UPI ID: {UPI_ID}\n\n"
        "**Payment Instructions:**\n"
        "1️⃣ 'Pay Now (UPI)' dabao ya QR scan karo\n"
        f"2️⃣ Exactly ₹{plan['price']} pay karo\n"
        "3️⃣ Payment ke baad 'Send Payment Proof' dabao\n\n"
        "⚠️ Proof verify hone ke baad premium activate ho jaayega."
    )
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton(
        "🌐 Pay Now (UPI)", url=payment_page_url(plan["price"])))
    markup.add(types.InlineKeyboardButton(
        "📲 Scan to Pay", callback_data=f"scanqr:{order_id}"))
    markup.add(types.InlineKeyboardButton(
        "📤 Send Payment Proof", callback_data=f"paid:{order_id}"))
    markup.add(types.InlineKeyboardButton(
        "❌ CANCEL ORDER", callback_data=f"cancelorder:{order_id}"))

    try:
        bot.send_photo(
            chat_id,
            upi_qr(plan["price"], f"Premium {order_id}"),
            caption=caption,
            reply_markup=markup,
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"[premium] QR send fail: {e}")
        bot.send_message(
            chat_id,
            caption + f"\n\nUPI ID: {UPI_ID}",
            reply_markup=markup,
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("pay:"))
def cb_pay(call):
    bot.answer_callback_query(call.id, "QR ban raha hai...")
    start_payment(call.message.chat.id, call.from_user.id, call.data.split(":", 1)[1])


@bot.callback_query_handler(func=lambda call: call.data == "scanqr")
def cb_scan_qr_plain(call):
    bot.answer_callback_query(call.id)
    try:
        bot.send_photo(
            call.message.chat.id,
            SCAN_QR_URL,
            caption=(
                "📲 **Scan to Pay**\n\n"
                f"🏦 UPI ID: {UPI_ID}\n"
                "Kisi bhi UPI app se QR scan karo.\n"
                "Payment ke baad 'Send Payment Proof' bhejo."
            ),
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"[premium] scan qr fail: {e}")
        bot.send_message(call.message.chat.id, f"🏦 UPI ID: {UPI_ID}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("scanqr:"))
def cb_scan_qr_order(call):
    order_id = call.data.split(":", 1)[1]
    order = store.get_order(order_id)
    bot.answer_callback_query(call.id)

    if order:
        caption = (
            "📲 **Scan to Pay**\n\n"
            f"💰 Amount: ₹{order.get('price')}\n"
            f"📅 Validity: {_validity_text(order.get('days', 0))}\n"
            f"🧾 Order ID: {order_id}\n"
            f"🏦 UPI ID: {UPI_ID}\n\n"
            "Payment ke baad 'Send Payment Proof' bhejo."
        )
    else:
        caption = f"📲 **Scan to Pay**\n\n🏦 UPI ID: {UPI_ID}"

    try:
        bot.send_photo(
            call.message.chat.id, SCAN_QR_URL, caption=caption, parse_mode="Markdown"
        )
    except Exception as e:
        print(f"[premium] scan qr fail: {e}")
        bot.send_message(call.message.chat.id, caption, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith("checkpay:"))
def cb_checkpay(call):
    order_id = call.data.split(":", 1)[1]
    order = store.get_order(order_id)
    if not order:
        bot.answer_callback_query(call.id, "Order nahi mila.", show_alert=True)
        return
    if order.get("status") == "approved":
        bot.answer_callback_query(call.id, "✅ Payment already verified!", show_alert=True)
        return
    if _rzp_order_paid(order):
        activate_order(order_id, source="manual-check")
        bot.answer_callback_query(call.id, "✅ Payment mil gaya! Premium active.", show_alert=True)
    else:
        bot.answer_callback_query(
            call.id, "Abhi payment nahi mili. 30 second baad try karo.", show_alert=True
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("cancelorder:"))
def cb_cancel_order(call):
    order_id = call.data.split(":", 1)[1]
    store.set_order_status(order_id, "cancelled")
    bot.answer_callback_query(call.id, "Order cancel ho gaya.")
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    awaiting_utr.pop(call.from_user.id, None)
    bot.send_message(
        call.message.chat.id,
        "❌ Payment process cancelled. Naya order start karne ke liye /premium bhejo.",
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("paid:"))
def cb_paid(call):
    order_id = call.data.split(":", 1)[1]
    order = store.get_order(order_id)
    if not order or order.get("status") in ("cancelled", "approved"):
        bot.answer_callback_query(
            call.id, "Ye order valid nahi hai. /premium se naya order banao.", show_alert=True
        )
        return
    awaiting_utr[call.from_user.id] = (order_id, time.time())
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "🧾 Apna **UTR / Transaction ID** (12 digit) bhejo, ya payment ka screenshot bhejo.\n\n"
        f"Order ID: {order_id}",
        parse_mode="Markdown",
    )


def _looks_like_proof(message):
    """Sirf real proof (photo ya UTR jaisa text) accept karo —
    buttons/commands ko UTR mat samajho."""
    if getattr(message, "photo", None):
        return True
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return False
    if text in ("📥 Download", "📊 Status", "💎 Premium"):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9]{8,22}", text))


@bot.message_handler(
    content_types=['photo', 'text'],
    func=lambda m: m.from_user.id in awaiting_utr and _looks_like_proof(m),
)
def handle_utr(message):
    saved = awaiting_utr.pop(message.from_user.id, None)
    if not saved:
        return
    order_id, started_at = saved
    if time.time() - started_at > 15 * 60:
        bot.send_message(
            message.chat.id,
            "⌛ Proof bhejne ka time nikal gaya. 'Send Payment Proof' dobara dabao.",
        )
        return
    order = store.get_order(order_id)
    if not order:
        bot.send_message(message.chat.id, "Order nahi mila. /premium se naya order banao.")
        return

    utr = (message.text or "").strip() or "(screenshot)"
    store.save_order(order_id, {
        "utr": utr,
        "status": "claimed",
        "claimed_at": _now().isoformat(),
    })

    bot.send_message(
        message.chat.id,
        "✅ Payment claim mil gaya!\n\n"
        "Verify hone me 5-10 minute lag sakte hain. Approve hote hi premium activate ho jaayega.",
    )

    owner_text = (
        "🔔 NEW PAYMENT CLAIM\n\n"
        f"User: {message.from_user.first_name} (id: {message.from_user.id})\n"
        f"Order: {order_id}\n"
        f"Amount: Rs {order.get('price')}\n"
        f"Days: {order.get('days')}\n"
        f"UTR / Note: {utr}"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Approve", callback_data=f"approve:{order_id}"),
        types.InlineKeyboardButton("❌ Reject", callback_data=f"reject:{order_id}"),
    )

    try:
        if message.photo:
            bot.send_photo(
                OWNER_ID, message.photo[-1].file_id,
                caption=owner_text, reply_markup=markup,
            )
        else:
            bot.send_message(OWNER_ID, owner_text, reply_markup=markup)
    except Exception as e:
        print(f"[premium] owner notify fail: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith(("approve:", "reject:")))
def cb_verify(call):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "Sirf owner ye kar sakta hai.", show_alert=True)
        return

    action, order_id = call.data.split(":", 1)
    order = store.get_order(order_id)
    if not order:
        bot.answer_callback_query(call.id, "Order nahi mila.", show_alert=True)
        return

    user_id = order.get("user_id")
    if action == "approve":
        until = grant_premium(user_id, order.get("days", 0))
        store.set_order_status(order_id, "approved")
        bot.answer_callback_query(call.id, "Approved ✅")
        try:
            bot.send_message(
                user_id,
                "✅ **Payment mil gaya!**\n\n"
                f"💎 Premium: {_expiry_text(until, order.get('days', 0))}\n\n"
                "Ab unlimited downloads — enjoy! 🚀",
                parse_mode="Markdown",
            )
        except Exception as e:
            print(f"[premium] user notify fail: {e}")
    else:
        store.set_order_status(order_id, "rejected")
        bot.answer_callback_query(call.id, "Rejected ❌")
        try:
            bot.send_message(
                user_id,
                "❌ Payment verify nahi hua.\n\n"
                f"Agar paisa cut gaya hai to support pe message karo: {SUPPORT_LINK}\n"
                f"Order ID: {order_id}",
            )
        except Exception as e:
            print(f"[premium] user notify fail: {e}")

    label = "✅ APPROVED" if action == "approve" else "❌ REJECTED"
    try:
        if call.message.caption is not None:
            bot.edit_message_caption(
                caption=call.message.caption + "\n\n" + label,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
            )
        else:
            bot.edit_message_text(
                text=(call.message.text or "") + "\n\n" + label,
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
            )
    except Exception:
        pass


@bot.message_handler(commands=['grant'])
def cmd_grant(message):
    """/grant <user_id> <days>"""
    if message.from_user.id != OWNER_ID:
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        bot.send_message(message.chat.id, "Use: /grant <user_id> <days>")
        return
    try:
        user_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        bot.send_message(message.chat.id, "user_id aur days number hone chahiye.")
        return
    until = grant_premium(user_id, days)
    bot.send_message(
        message.chat.id,
        f"✅ {user_id} ko {days} din ka premium diya. Expiry: {until.strftime('%d %b %Y, %I:%M %p')} UTC",
    )
    try:
        bot.send_message(
            user_id,
            f"💎 Premium activated! Valid till {until.strftime('%d %b %Y, %I:%M %p')} (UTC).",
        )
    except Exception:
        pass


@bot.message_handler(commands=['revoke'])
def cmd_revoke(message):
    """/revoke <user_id>"""
    if message.from_user.id != OWNER_ID:
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        bot.send_message(message.chat.id, "Use: /revoke <user_id>")
        return
    try:
        user_id = int(parts[1])
    except ValueError:
        bot.send_message(message.chat.id, "user_id number hona chahiye.")
        return
    revoke_premium(user_id)
    bot.send_message(message.chat.id, f"✅ {user_id} ka premium hata diya.")


# ================= BOT UI =================
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("📥 Download"),
        types.KeyboardButton("📊 Status"),
        types.KeyboardButton("💎 Premium")
    )
    return markup

@bot.message_handler(commands=['start'])
def start_command(message):
    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""
    if payload.startswith("verify_"):
        handle_verify_payload(message, payload[len("verify_"):])
        return

    asyncio.run_coroutine_threadsafe(_send_start_to_target(), loop)

    welcome_text = (
        "🔥 **Faphouse Downloader Bot** — by @ModAppsKing\n\n"
        "📥 Bas apna **Faphouse link** bhejo, baaki mera kaam!\n"
        "Download + Upload — sab automatic. ⚡\n\n"
        "✅ **Ye links chalte hai:**\n"
        "• `faphouse.com` / `faphouse2.com` waale links\n\n"
        "⚡ Fast • 💪 Reliable • 🆓 Free\n"
        "🚀 Powered by @ModAppsKing"
    )
    bot.send_message(
        message.chat.id, 
        welcome_text,
        reply_markup=get_main_keyboard(),
        parse_mode="Markdown"
    )
    bot.send_message(
        message.chat.id,
        f"🎁 Pehle {FREE_TRIAL_DOWNLOADS} videos free! Uske baad ads verify karke "
        f"{ADS_REWARD_DOWNLOADS} aur downloads — ya /premium se unlimited.\n\n"
        "👇 Apna Faphouse link bhejo boss!",
    )

@bot.message_handler(func=lambda msg: msg.text == "📥 Download")
def handle_download_btn(message):
    text = (
        "📥 **Ready to Roll!**\n\n"
        "Bhai 2026 me bhi bot zinda hai — aur pehle se zyada fast! 😎\n"
        "Link daalo, download pakdo! 🚀\n\n"
        "✅ **Ye links supported hai:**\n"
        "• `faphouse.com` / `faphouse2.com` waale links\n\n"
        "👇 **Bas link paste karo aur dekhte jao!**"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💎 Buy Premium", callback_data="premium_menu"))
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text == "📊 Status")
def handle_status_btn(message):
    uid = message.chat.id
    until = premium_until(uid)
    user = store.get_user(uid)

    if until:
        plan_line = _plan_line(until)
        usage_line = "Unlimited"
    else:
        plan_line = "🆓 Free"
        usage_line = (
            f"{usage_today(uid)}/{FREE_DAILY_LIMIT}"
            if FREE_DAILY_LIMIT > 0 else "Unlimited"
        )

    text = (
        "📊 **Live Status Dashboard**\n\n"
        f"🤖 **Bot:** {MAIN_BOT_NAME}\n\n"
        "👤 **Aapka Profile:**\n"
        f"🏷 **Plan:** {plan_line}\n"
        f"📥 **Aaj ke downloads:** {usage_line}\n"
        f"🎁 **Downloads left:** {downloads_left_text(uid)}\n"
        f"✅ **Total Downloads:** {int(user.get('total_downloads', 0))}\n\n"
        "💡 _Download atak gaya? /cancel bhejo — sab reset!_"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💎 Buy Premium", callback_data="premium_menu"))
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: "http" in msg.text)
def handle_faphouse_link(message):
    user_requests[message.chat.id] = message.text
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(types.InlineKeyboardButton("🚀 Open in TeraPlay", url=TERAPLAY_LINK))
    markup.add(types.InlineKeyboardButton("📥 Download Video on Telegram", callback_data="download_video"))
    
    bot.send_message(
        message.chat.id,
        "**▶️ Any Play**\n"
        "**Stream Any Video Easily**\n\n"
        "⚡ Faster streaming\n"
        "📺 Better viewing experience\n"
        "✨ Smooth playback inside the app\n\n"
        "**Highly recommended:** tap **Open in TeraPlay** to watch in the app.\n\n"
        "📥 If you want to download the video on Telegram instead, tap **Download Video on Telegram**.",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: call.data == "download_video")
def process_download(call):
    chat_id = call.message.chat.id
    
    if chat_id not in user_requests:
        bot.answer_callback_query(call.id, "❌ Link expire ho gaya hai, wapas link bhejein.", show_alert=True)
        return
        
    url = user_requests[chat_id]
    
    allowed, info = consume_download(chat_id)
    if not allowed:
        if info == "verify":
            link, _ = create_verify_link(chat_id)
            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("🔓 Verify Now (Ads)", url=link))
            markup.add(types.InlineKeyboardButton(
                "💎 Go Premium (Unlimited)", callback_data="premium_menu"))
            try:
                bot.answer_callback_query(call.id, "Verification required", show_alert=False)
            except Exception:
                pass
            bot.send_message(
                chat_id,
                f"🔒 **Aapke {FREE_TRIAL_DOWNLOADS} free videos khatam ho gaye!**\n\n"
                "Neeche wale link se ads complete karo aur "
                f"**{ADS_REWARD_DOWNLOADS} aur downloads** paao.\n\n"
                "⚡ Ya phir Premium lo — unlimited, bina ads.",
                reply_markup=markup,
                parse_mode="Markdown",
            )
        else:
            bot.answer_callback_query(
                call.id,
                f"Aaj ki free limit ({FREE_DAILY_LIMIT}) khatam. /premium lo.",
                show_alert=True,
            )
        return

    plan_markup = types.InlineKeyboardMarkup()
    plan_markup.add(types.InlineKeyboardButton("💎 Buy Premium - No Waiting!", callback_data="premium_menu"))
    
    try:
        bot.answer_callback_query(call.id, "⏳ Download shuru ho raha hai...")
    except Exception:
        pass

    try:
        bot.edit_message_text(
            SPINNER_TEXT.format(bar=BAR_FRAMES[0]),
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=plan_markup,
            parse_mode="Markdown",
        )
    except Exception as e:
        print(f"Edit msg error: {e}")

    # Loading animation chalu — koi bhi agla update isse khud rok dega
    start_spinner(chat_id, call.message.message_id)

    with processing_lock:
        asyncio.run_coroutine_threadsafe(_fetch_from_target(url, chat_id, call.message.message_id), loop)


# ================= INTERNAL ROUTING =================
@bot.message_handler(func=lambda msg: msg.text and msg.text.startswith("DELIVER "))
def handle_delivery(message):
    if message.from_user.id != OWNER_ID:
        return

    try:
        target_user_id = int(message.text.split()[1])
        
        if not message.reply_to_message:
            return
            
        video_msg_id = message.reply_to_message.message_id
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💎 Buy Premium", callback_data="premium_menu"))
        
        sent = bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=message.chat.id,
            message_id=video_msg_id,
            reply_markup=markup
        )

        # Target bot ka caption + cover hata kar apna lagao
        caption = build_video_caption(sent)
        media_edited = False

        if REPLACE_COVER and COVER_URL and getattr(sent, "video", None):
            try:
                media = types.InputMediaVideo(
                    media=sent.video.file_id,
                    caption=caption,
                    width=getattr(sent.video, "width", None),
                    height=getattr(sent.video, "height", None),
                    duration=getattr(sent.video, "duration", None),
                    supports_streaming=True,
                    cover=COVER_URL,
                )
                bot.edit_message_media(
                    media=media,
                    chat_id=target_user_id,
                    message_id=sent.message_id,
                    reply_markup=markup,
                )
                media_edited = True
                print(f"[cover] cover badal diya (msg {sent.message_id})")
            except Exception as e:
                print(f"[cover] edit_message_media fail: {e}")

        if not media_edited:
            try:
                bot.edit_message_caption(
                    caption=caption,
                    chat_id=target_user_id,
                    message_id=sent.message_id,
                    reply_markup=markup
                )
            except Exception as e:
                print(f"[caption] {e}")

        schedule_auto_delete(target_user_id, sent.message_id, AUTO_DELETE_SECONDS)
        
    except Exception as e:
        print(f"❌ Fatal Route Error: {e}")


# ================= DUMMY HTTP SERVER =================
def run_dummy_server():
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def _plain(self, code, text):
            self.send_response(code)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(text.encode())

        def do_GET(self):
            self._plain(200, "Bot is running!")

        def do_POST(self):
            # Razorpay webhook endpoint
            if self.path.split("?")[0] != "/razorpay-webhook":
                self._plain(404, "not found")
                return

            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            body = self.rfile.read(length) if length else b""
            signature = self.headers.get("X-Razorpay-Signature", "")

            if not _verify_webhook(body, signature):
                self._plain(400, "invalid signature")
                return

            self._plain(200, "ok")
            try:
                _handle_rzp_event(json.loads(body or b"{}"))
            except Exception as e:
                print(f"[webhook] handle fail: {e}")

        def log_message(self, *args):
            pass

    try:
        server = HTTPServer(('0.0.0.0', PORT), Handler)
        print(f"HTTP server running on port {PORT} (webhook: /razorpay-webhook)")
        server.serve_forever()
    except OSError:
        pass

threading.Thread(target=run_dummy_server, daemon=True).start()
# ====================================================

# ================= MAIN LOOP =================
if __name__ == "__main__":
    print("Main Bot is Live!")
    bot.remove_webhook()
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except KeyboardInterrupt:
            print("\nBot stopped.")
            loop.stop()
            break
        except Exception as e:
            print(f"[fatal polling error] {e} — 5 sec me restart ho raha hai...")
            time.sleep(5)
            continue
