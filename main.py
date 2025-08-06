import os
import tempfile
import cv2
import numpy as np
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# Telegram & Webhook 設定
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]

# OpenAI 金鑰
openai.api_key = os.environ["OPENAI_API_KEY"]

# 使用者預測記憶
user_last_prediction = {}

# 啟動指令
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，我是百家樂預測機器人（GPT 版）！請傳牌路圖片給我分析。")

# 解析圖片為莊/閒
def analyze_baccarat_image(image_path: str, cell_size=30):
    image = cv2.imread(image_path)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    lower_red1 = np.array([0, 100, 100])
    upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([160, 100, 100])
    upper_red2 = np.array([179, 255, 255])
    lower_blue = np.array([100, 150, 0])
    upper_blue = np.array([140, 255, 255])
    lower_green = np.array([40, 40, 40])
    upper_green = np.array([90, 255, 255])

    red_mask = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
    blue_mask = cv2.inRange(hsv, lower_blue, upper_blue)
    green_mask = cv2.inRange(hsv, lower_green, upper_green)

    contours_red = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    contours_blue = cv2.findContours(blue_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    contours_green = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]

    points = []

    def process_contours(contours, label):
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            col = x // cell_size
            row = y // cell_size
            points.append((label, col, row))

    process_contours(contours_red, '莊')
    process_contours(contours_blue, '閒')
    process_contours(contours_green, '和')

    max_col = max([p[1] for p in points], default=0) + 1
    max_row = max([p[2] for p in points], default=0) + 1
    grid = [['' for _ in range(max_col)] for _ in range(max_row)]

    for label, col, row in points:
        grid[row][col] = label

    columns = []
    for col in range(max_col):
        column = []
        for row in range(max_row):
            if grid[row][col]:
                column.append(grid[row][col])
        if column:
            columns.append(column)

    return [x for col in columns for x in col if x in ["莊", "閒"]]

# GPT 模型預測邏輯
def ask_gpt_prediction(history_list):
    prompt = (
        f"你是百家樂走勢分析師，根據以下莊閒紀錄判斷下一顆可能出現的是「莊」或「閒」。\n\n"
        f"牌路紀錄：{history_list}\n\n"
        f"請根據趨勢、連續、反彈等特性，做出預測，回覆格式如下：\n"
        f"✅ 預測：莊\n"
        f"📊 勝率：莊 52.0%、閒 48.0%\n"
        f"🧠 統合分析：根據近期莊方連續性與副路紅偏，預測莊方續勢。\n\n"
        f"請用類似格式回覆："
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "你是專業的百家樂趨勢預測助手。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()
        return reply
    except Exception as e:
        return f"⚠️ GPT 分析失敗：{e}"

# 圖片處理主流程
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 圖片已接收，開始分析...")

    user_id = update.message.from_user.id

    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_image:
        temp_image.write(image_bytes)
        temp_path = temp_image.name

    try:
        history = analyze_baccarat_image(temp_path)

        if len(history) < 5:
            await update.message.reply_text("⚠️ 資料太少無法分析，請提供更多牌路圖片。")
            return

        gpt_reply = ask_gpt_prediction(history)
        await update.message.reply_text(gpt_reply)

        if "莊" in gpt_reply and "預測：莊" in gpt_reply:
            user_last_prediction[user_id] = "莊"
        elif "閒" in gpt_reply and "預測：閒" in gpt_reply:
            user_last_prediction[user_id] = "閒"
        else:
            user_last_prediction[user_id] = None

    except Exception as e:
        await update.message.reply_text(f"⚠️ 分析錯誤：{e}")

# 回報實際結果學習
async def handle_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    args = context.args

    if not args or args[0] not in ["莊", "閒"]:
        await update.message.reply_text("請使用格式：/result 莊 或 /result 閒")
        return

    actual = args[0]
    predicted = user_last_prediction.get(user_id)

    if not predicted:
        await update.message.reply_text("⚠️ 尚未有預測紀錄，請先傳圖片分析。")
        return

    if actual == predicted:
        await update.message.reply_text("✅ 預測正確，已記錄這次成功！")
    else:
        await update.message.reply_text("❌ 預測錯誤，下次再努力！")

    user_last_prediction.pop(user_id)

# 建立機器人應用
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("result", handle_result))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

# 啟動 Webhook
app.run_webhook(
    listen="0.0.0.0",
    port=10000,
    webhook_url=WEBHOOK_URL
)
