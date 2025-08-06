import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
OCR_API_KEY = os.environ.get("OCR_API_KEY") or "helloworld"  # OCR.space 免費 key

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，我是百家樂預測機器人！請傳牌路圖片給我分析。")

def ocr_image_by_bytes(image_bytes):
    api_url = "https://api.ocr.space/parse/image"
    files = {
        'file': ('image.jpg', image_bytes)
    }
    payload = {
        'apikey': OCR_API_KEY,
        'language': 'eng',
        'isOverlayRequired': False
    }

    response = requests.post(api_url, files=files, data=payload)
    result = response.json()

    # 顯示完整結果供除錯
    print("🔍 OCR 回傳內容：", result)

    if "ParsedResults" in result and result["ParsedResults"]:
        return result["ParsedResults"][0].get("ParsedText", "❌ 找不到文字")
    else:
        error_message = result.get("ErrorMessage") or result.get("OCRExitCode")
        return f"❌ 分析失敗：{error_message or '無法取得結果'}"

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 圖片已接收，開始分析...")

    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()

    ocr_result = ocr_image_by_bytes(image_bytes)

    await update.message.reply_text(f"🧾 OCR結果：\n{ocr_result}")

# 建立應用程式
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

# Webhook 模式啟動
app.run_webhook(
    listen="0.0.0.0",
    port=10000,
    webhook_url=WEBHOOK_URL
)
