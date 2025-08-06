from telegram.ext import MessageHandler, filters

# 圖片處理函式
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_file = await update.message.photo[-1].get_file()
    await photo_file.download_to_drive("received.jpg")
    await update.message.reply_text("圖片已接收，開始分析...")

# 註冊圖片處理器
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
