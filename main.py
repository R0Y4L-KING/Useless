import threading
import asyncio
import os
import time
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
# ===================================================================

bot = telebot.TeleBot(BOT_TOKEN)

try:
    MAIN_BOT_USERNAME = f"@{bot.get_me().username}"
    print(f"Bot Username detected as: {MAIN_BOT_USERNAME}")
except Exception as e:
    print(f"Error fetching bot username: {e}")
    MAIN_BOT_USERNAME = "@YourBotUsername"

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
    if delay <= 0:
        return

    def job():
        try:
            bot.delete_message(chat_id, message_id)
            print(f"[auto-delete] message {message_id} deleted")
        except Exception as e:
            print(f"[auto-delete] {e}")

    t = threading.Timer(delay, job)
    t.daemon = True
    t.start()


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
                    plan_markup.add(types.InlineKeyboardButton("💎 Buy Premium", url=PLAN_LINK))
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


# ================= BOT UI =================
def get_main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("📥 Download"),
        types.KeyboardButton("📊 Status")
    )
    return markup

@bot.message_handler(commands=['start'])
def start_command(message):
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
    bot.send_message(message.chat.id, "👇 Apna Faphouse link bhejo boss!")

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
    markup.add(types.InlineKeyboardButton("💎 Buy Premium", url=PLAN_LINK))
    
    bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text == "📊 Status")
def handle_status_btn(message):
    text = (
        "📊 **Live Status Dashboard**\n\n"
        "🤖 **Bot:** bot1\n"
        "🔄 **Active Tasks (Global):** 0/10\n\n"
        "👤 **Aapka Profile:**\n"
        "🏷 **Plan:** 🆓 Free\n"
        "📥 **Chal rahe Downloads:** 0/2\n"
        "✅ **Total Downloads:** 2\n\n"
        "💡 _Download atak gaya? /cancel bhejo — sab reset!_"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💎 Buy Premium", url=PLAN_LINK))
    
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
    
    plan_markup = types.InlineKeyboardMarkup()
    plan_markup.add(types.InlineKeyboardButton("💎 Buy Premium - No Waiting!", url=PLAN_LINK))
    
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
        markup.add(types.InlineKeyboardButton("💎 Buy Premium", url=PLAN_LINK))
        
        sent = bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=message.chat.id,
            message_id=video_msg_id,
            reply_markup=markup
        )

        # Target bot ka caption hata kar apna caption lagao
        caption = build_video_caption(sent)
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
    class PingHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Bot is running!")
    try:
        server = HTTPServer(('0.0.0.0', PORT), PingHandler)
        print(f"Dummy HTTP server running on port {PORT}")
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
