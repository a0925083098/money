import os
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters
)

# 環境變數取得 Token
BOT_TOKEN = os.getenv("BOT_TOKEN")

# 處理訊息的函式
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.reply_text(f"你說了：{user_message}")

# 建立應用程式
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

if __name__ == '__main__':
    print("✅ Bot 正在啟動中...")
    app.run_polling()
