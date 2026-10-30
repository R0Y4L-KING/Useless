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

# Custom Links
TERAPLAY_LINK = "https://play.google.com/store/apps/details?id=in.shadowlink.anyplay"
PLAN_LINK = "https://t.me/R0Y4L_KING"
PORT = int(os.environ.get('PORT', '8080'))
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
                try:
                    bot.edit_message_text(
                        "❌ **Download Failed!**\n\nTarget server par issue hai. Kripya koi dusra link try karein.",
                        chat_id=user_chat_id,
                        message_id=call_msg_id,
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
                return False

            # ---> CASE B: PROGRESS BAR MIRRORING <---
            if msg.text and ("Progress" in msg.text or "Speed:" in msg.text or "ETA:" in msg.text):
                progress_text = msg.text
                if progress_text != last_progress_text:
                    try:
                        plan_markup = types.InlineKeyboardMarkup()
                        plan_markup.add(types.InlineKeyboardButton("💎 Buy Premium", url=PLAN_LINK))
                        
                        bot.edit_message_text(
                            text=f"{progress_text}\n\n⚡ Multiple videos ek saath download karna hai?\nPremium le lo!",
                            chat_id=user_chat_id,
                            message_id=call_msg_id,
                            reply_markup=plan_markup
                        )
                        last_progress_text = progress_text
                    except Exception:
                        pass
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
                    
                    try:
                        bot.edit_message_text(
                            "✅ **Video Uploading Finished!**",
                            chat_id=user_chat_id,
                            message_id=call_msg_id,
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass
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
                                        
                                        try:
                                            bot.edit_message_text(
                                                "⏳ **Video server par connect ho rahi hai...**",
                                                chat_id=user_chat_id,
                                                message_id=call_msg_id,
                                                parse_mode="Markdown"
                                            )
                                        except Exception:
                                            pass
                                    except Exception as e:
                                        print(f"Quality click error: {e}")
                                    break
                            if clicked: break
                        if clicked: break
                
    print("[telethon] Error: Video aane me timeout ho gaya.")
    try:
        bot.edit_message_text(
            "❌ **Timeout Error**\n\nVideo download hone me bohot zyada time lag gaya. Please try again later.",
            chat_id=user_chat_id,
            message_id=call_msg_id,
            parse_mode="Markdown"
        )
    except Exception:
        pass
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
        "🔥 **Faphouse Downloader Bot** — by YourBrand\n\n"
        "📥 Bas apna **Faphouse link** bhejo, baaki mera kaam!\n"
        "Download + Upload — sab automatic. ⚡\n\n"
        "✅ **Ye links chalte hai:**\n"
        "• `faphouse.com` / `faphouse2.com` waale links\n\n"
        "⚡ Fast • 💪 Reliable • 🆓 Free\n"
        "🚀 Powered by YourBrand"
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
        bot.edit_message_text(
            "⏳ **Wait karo, download connect ho raha hai...**\n\n"
            "💎 **Premium lo — no waiting, instant downloads!**",
            chat_id=chat_id,
            message_id=call.message.message_id,
            reply_markup=plan_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Edit msg error: {e}")
    
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
        
        bot.copy_message(
            chat_id=target_user_id,
            from_chat_id=message.chat.id,
            message_id=video_msg_id,
            reply_markup=markup
        )
        
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
            