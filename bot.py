import os
import subprocess
import threading
import time
import asyncio
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)

# ============================================================
# ====== الإعدادات ======
# ============================================================
BOT_TOKEN    = os.environ.get("8987034007:AAGw4WSJv3iZX23cJsWzTeCEdQu_MyoQNQY")
PASSWORD_CMD = ".ismail"
MAX_STREAMS  = 5
STREAM_DELAY = 5

# ============================================================
# ====== الحالة ======
# ============================================================
active_streams = {}
user_sessions  = {}
lock           = threading.Lock()

def get_session(chat_id):
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {
            "auth": False,
            "state": "idle",
            "total": 0,
            "index": 0,
            "step": "key",
            "streams": []
        }
    return user_sessions[chat_id]

# ============================================================
# ====== FFmpeg ======
# ============================================================
def start_ffmpeg(stream_key, source_url, stream_name):
    cmd = [
        "ffmpeg", "-re",
        "-i", source_url,
        "-c:v", "copy",
        "-c:a", "aac",
        "-ar", "44100",
        "-ab", "128k",
        "-ac", "2",
        "-f", "flv",
        stream_key
    ]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with lock:
            name = stream_name
            if name in active_streams:
                name = f"{name} ({int(time.time()) % 1000})"
            active_streams[name] = proc
        return True, name, None
    except Exception as e:
        return False, stream_name, str(e)

def launch_all_streams(streams):
    results = []
    threads = []
    def worker(s):
        ok, name, err = start_ffmpeg(s["key"], s["link"], s["name"])
        results.append((ok, name, err))
    for s in streams:
        t = threading.Thread(target=worker, args=(s,))
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results

# ============================================================
# ====== الأوامر ======
# ============================================================
async def cmd_ismail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    session["auth"] = True
    await update.message.reply_text(
        "🔑 تم التحقق.\n"
        f"كم بث تريد تشغيل؟ (حد أقصى {MAX_STREAMS})\n"
        "مثال: .3 أو .4"
    )

async def cmd_9an(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session["auth"]:
        await update.message.reply_text(f"⚠️ أرسل {PASSWORD_CMD} أولاً.")
        return
    with lock:
        names = list(active_streams.keys())
    if not names:
        await update.message.reply_text("📭 ماكاين حتى بث خدام دابا.")
    else:
        msg = "📺 القنوات لي خدامين دابا:\n" + "\n".join(f"• {n}" for n in names)
        await update.message.reply_text(msg)

async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    session = get_session(chat_id)
    if not session["auth"]:
        await update.message.reply_text(f"⚠️ أرسل {PASSWORD_CMD} أولاً.")
        return
    arg = " ".join(context.args).strip() if context.args else None
    with lock:
        if not arg:
            if not active_streams:
                await update.message.reply_text("📭 ماكاين حتى بث خدام باش نوقف.")
                return
            stopped = []
            for name, proc in list(active_streams.items()):
                try:
                    proc.terminate()
                    stopped.append(name)
                except Exception as e:
                    print(f"[stop] {name}: {e}")
            active_streams.clear()
            msg = f"🛑 توقفو {len(stopped)} بث:\n" + "\n".join(f"• {n}" for n in stopped)
            await update.message.reply_text(msg)
            return
        names = list(active_streams.keys())
        target = None
        if arg in active_streams:
            target = arg
        else:
            matches = [n for n in names if arg.lower() in n.lower()]
            if len(matches) == 1:
                target = matches[0]
            elif len(matches) > 1:
                msg = "⚠️ كاين أكثر من قناة بهاد الاسم، حدد وحدة بالضبط:\n"
                msg += "\n".join(f"• {n}" for n in matches)
                await update.message.reply_text(msg)
                return
        if target is None and arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(names):
                target = names[idx]
        if target is None:
            await update.message.reply_text(
                f"⚠️ مالقيتش قناة اسمها «{arg}».\n"
                "أرسل .9an باش تشوف الأسماء لي خدامين."
            )
            return
        try:
            active_streams[target].terminate()
            del active_streams[target]
            await update.message.reply_text(f"🛑 توقفت القناة: {target}")
        except Exception as e:
            await update.message.reply_text(f"❌ خطأ فإيقاف «{target}»: {e}")

# ============================================================
# ====== معالج الرسائل النصية ======
# ============================================================
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    session = get_session(chat_id)
    if text == PASSWORD_CMD:
        await cmd_ismail(update, context)
        return
    if not session["auth"]:
        await update.message.reply_text(f"⚠️ أرسل {PASSWORD_CMD} أولاً.")
        return
    if session["state"] == "idle":
        if text.startswith(".") and text[1:].isdigit():
            n = int(text[1:])
            if not (1 <= n <= MAX_STREAMS):
                await update.message.reply_text(f"⚠️ العدد خاصو يكون بين 1 و {MAX_STREAMS}.")
                return
            with lock:
                current = len(active_streams)
            if current + n > MAX_STREAMS:
                await update.message.reply_text(f"⚠️ كاين {current} بث خدام دابا. الحد الأقصى {MAX_STREAMS}.")
                return
            session.update({"state": "collecting", "total": n, "index": 0, "step": "key", "streams": []})
            await update.message.reply_text(f"✅ غادي نجمع {n} بث.\n\n🔑 أرسل مفتاح البث رقم 1")
            return
        await update.message.reply_text("ℹ️ أرسل عدد البثوث بحال .3 أو .4")
        return
    i = session["index"] + 1
    if session["step"] == "key":
        if not text.startswith("rtmp"):
            await update.message.reply_text("⚠️ المفتاح خاصو يبدا بـ rtmp:// أو rtmps://")
            return
        session["streams"].append({"key": text, "link": "", "name": ""})
        session["step"] = "link"
        await update.message.reply_text(f"🔗 أرسل رابط البث رقم {i} (m3u8 أو ts)")
        return
    if session["step"] == "link":
        if not text.startswith("http"):
            await update.message.reply_text("⚠️ الرابط خاصو يبدا بـ http")
            return
        session["streams"][-1]["link"] = text
        session["step"] = "name"
        await update.message.reply_text(f"📝 أرسل اسم القناة رقم {i}")
        return
    if session["step"] == "name":
        session["streams"][-1]["name"] = text
        session["index"] += 1
        if session["index"] < session["total"]:
            nxt = session["index"] + 1
            session["step"] = "key"
            await update.message.reply_text(f"🔑 أرسل مفتاح البث رقم {nxt}")
            return
        streams = session["streams"][:]
        session.update({"state": "idle", "streams": [], "total": 0, "index": 0, "step": "key"})
        await update.message.reply_text(f"✅ تجمعو {len(streams)} بث.\n⏳ انتظر {STREAM_DELAY} ثواني... سيتم إطلاق كلشي فنفس اللحظة.")
        async def delayed():
            await asyncio.sleep(STREAM_DELAY)
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, launch_all_streams, streams)
            lines = ["🚀 نتيجة الإطلاق:"]
            for ok, name, err in results:
                if ok:
                    lines.append(f"✅ {name}")
                else:
                    lines.append(f"❌ {name}: {err}")
            await update.message.reply_text("\n".join(lines))
        asyncio.create_task(delayed())
        return

# ============================================================
# ====== التشغيل ======
# ============================================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_ismail))
    app.add_handler(CommandHandler("ismail", cmd_ismail))
    app.add_handler(CommandHandler("9an", cmd_9an))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    print("🤖 البوت خدام... Ctrl+C للخروج")
    app.run_polling()

if __name__ == "__main__":
    main()
