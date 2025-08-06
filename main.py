import tempfile
import uuid

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 圖片已接收，開始分析...")

    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()

    # 暫存圖片到本地檔案
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_image:
        temp_image.write(image_bytes)
        temp_path = temp_image.name

    try:
        # 呼叫圖片辨識函數
        result = analyze_baccarat_image(temp_path)

        if not result:
            await update.message.reply_text("❌ 分析失敗，請確認圖片清晰並為牌路圖。")
            return

        # 預測下一顆（先用最後一欄最後一顆當簡單預測）
        last_column = result[-1] if result else []
        next_prediction = last_column[-1] if last_column else "未知"

        # 計算莊/閒的總數與比例
        flat = [x for col in result for x in col]
        banker_count = flat.count("莊")
        player_count = flat.count("閒")
        total = banker_count + player_count
        if total == 0:
            banker_rate = player_rate = 50.0
        else:
            banker_rate = round(banker_count / total * 100, 1)
            player_rate = round(player_count / total * 100, 1)

        # 回傳預測結果
        reply = (
            f"✅ 預測：{next_prediction}\n"
            f"📊 勝率：莊 {banker_rate}%、閒 {player_rate}%\n"
            f"🧠 策略分析：根據最後一欄趨勢，預測延續「{next_prediction}」。"
        )
        await update.message.reply_text(reply)

    except Exception as e:
        await update.message.reply_text(f"⚠️ 分析時發生錯誤：{e}")
