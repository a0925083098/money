import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
OCR_API_KEY = os.environ.get("OCR_API_KEY") or "helloworld"  # OCR.space 免費預設 key

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，我是百家樂預測機器人！請傳牌路圖片給我分析。")

def ocr_image_by_url(image_url):
    api_url = "https://api.ocr.space/parse/image"
    payload = {
        'apikey': OCR_API_KEY,
        'url': image_url,
        'language': 'eng',
        'isOverlayRequired': False
    }

    response = requests.post(api_url, data=payload)
    result = response.json()

    try:
        return result["ParsedResults"][0]["ParsedText"]
    except (KeyError, IndexError) as e:
        return f"❌ 分析失敗：{e}"

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 圖片已接收，開始分析...")

    photo_file = await update.message.photo[-1].get_file()
    image_url = photo_file.file_path  # Telegram 圖片網址

    ocr_result = ocr_image_by_url(image_url)

    await update.message.reply_text(f"🧾 OCR結果：\n{ocr_result}")

# 建立應用程式
app = ApplicationBuilder().token(BOT_TOKEN).build()

# 註冊指令與訊息處理器
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

# 啟動 Webhook 模式
app.run_webhook(
    listen="0.0.0.0",
    port=10000,
    webhook_url=WEBHOOK_URL
)
