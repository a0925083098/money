import os
import requests
from PIL import Image
from io import BytesIO
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
OCR_API_KEY = os.environ["OCR_API_KEY"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，我是百家樂預測機器人！")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 圖片已接收，開始分析...")

    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    # 呼叫 OCR.space API
    response = requests.post(
        "https://api.ocr.space/parse/image",
        files={"filename": photo_bytes},
        data={"apikey": OCR_API_KEY, "language": "eng"},
    )

    result = response.json()
    try:
        text = result["ParsedResults"][0]["ParsedText"]
        await update.message.reply_text(f"OCR結果：\n{text}")
    except Exception as e:
        await update.message.reply_text(f"❌ 分析失敗：{e}")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

app.run_webhook(
    listen="0.0.0.0",
    port=10000,
    webhook_url=WEBHOOK_URL
)
