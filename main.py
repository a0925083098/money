import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

# /start 指令
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，請傳一張百家樂牌路圖，我會幫你分析！")

# 接收圖片
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file = await update.message.photo[-1].get_file()
    file_path = f"downloaded_image.jpg"
    await photo_file.download_to_drive(file_path)

    # 回覆收到圖片
    await update.message.reply_text("✅ 圖片已接收，準備進行分析...")

    # 這裡可以加入未來的 OCR 分析或預測邏輯
    await update.message.reply_text("🧠（模擬）分析完成：\n✅ 預測：莊\n📊 勝率：莊 53.0%、閒 47.0%\n🧠 策略分析：根據當前連續趨勢，預測延續同方。")

# 建立應用程式
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

# Webhook 模式
app.run_webhook(
    listen="0.0.0.0",
    port=10000,
    webhook_url=WEBHOOK_URL
)
