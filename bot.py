import os
import asyncio
import tempfile

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.environ["BOT_TOKEN"]

MAX_IN = 20 * 1024 * 1024   # حد تليقرام للتنزيل: 20 ميجا
MAX_OUT = 50 * 1024 * 1024  # حد تليقرام للإرسال: 50 ميجا

# تحسين الفيديو: إزالة التشويش، تكبير الدقة (حد أقصى 1080)، زيادة الحدة، تحسين الألوان
VIDEO_FILTER = (
    "hqdn3d=3:2:4:3,"
    "scale=-2:min(1080\\,ih*2):flags=lanczos,"
    "unsharp=5:5:0.8:3:3:0.4,"
    "eq=contrast=1.05:saturation=1.1"
)

# معالجة فيديو واحد في الوقت نفسه عشان السيرفر ما يتعب
lock = asyncio.Semaphore(1)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً! 👋\n"
        "أرسل لي فيديو (حتى 20 ميجا) وأرجعه لك بجودة أحسن."
    )


async def enhance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    media = msg.video or msg.document
    if media is None:
        return

    # لو أرسل ملف مو فيديو
    if msg.document and not (msg.document.mime_type or "").startswith("video/"):
        await msg.reply_text("أرسل لي فيديو فقط 🎬")
        return

    if media.file_size and media.file_size > MAX_IN:
        await msg.reply_text("الفيديو كبير 😅 لازم يكون أقل من 20 ميجا.")
        return

    status = await msg.reply_text("جاري التحسين... ⏳ ممكن ياخذ دقيقة أو أكثر.")

    async with lock:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "input.mp4")
            dst = os.path.join(tmp, "output.mp4")

            tg_file = await media.get_file()
            await tg_file.download_to_drive(src)

            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y", "-i", src,
                "-vf", VIDEO_FILTER,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                dst,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(proc.wait(), timeout=900)
            except asyncio.TimeoutError:
                proc.kill()
                await status.edit_text("الفيديو أخذ وقت طويل وألغيته 😔 جرب فيديو أقصر.")
                return

            if proc.returncode != 0 or not os.path.exists(dst):
                await status.edit_text("صار خطأ أثناء المعالجة 😔 جرب فيديو ثاني.")
                return

            if os.path.getsize(dst) > MAX_OUT:
                await status.edit_text("الفيديو بعد التحسين صار أكبر من 50 ميجا، جرب فيديو أقصر.")
                return

            with open(dst, "rb") as f:
                await msg.reply_video(
                    video=f,
                    supports_streaming=True,
                    caption="تفضل ✨",
                    read_timeout=300,
                    write_timeout=300,
                )
            await status.delete()


def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, enhance))
    app.run_polling()


if __name__ == "__main__":
    main()
