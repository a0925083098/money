from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
import os

BOT_TOKEN = os.environ["BOT_TOKEN"]

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("機器人已啟動，收到你的訊息囉！")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("✅ 機器人正在執行...")
app.run_polling()
