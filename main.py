import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
OCR_API_KEY = os.environ["OCR_API_KEY"]  # 你要在 Render 設定這個環境變數

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，我是百家樂預測機器人！請傳一張牌路圖片給我。")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📷 圖片已接收，正在分析中...")

    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    # 上傳圖片到 OCR.space
    try:
        response = requests.post(
            "https://api.ocr.space/parse/image",
            files={"filename": photo_bytes},
            data={"apikey": OCR_API_KEY, "language": "eng"},
        )
        result = response.json()

        parsed_text = result["ParsedResults"][0]["ParsedText"]
        await update.message.reply_text(f"🧾 OCR結果：\n{parsed_text}")

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
