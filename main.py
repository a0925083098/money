import os
import tempfile
import cv2
import numpy as np
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

# ✅ 設定 API KEY
BOT_TOKEN = os.environ["BOT_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
openai.api_key = os.environ["OPENAI_API_KEY"]  # Render 設定變數

# ✅ Telegram 起始指令
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("你好，我是百家樂預測機器人！請傳牌路圖片給我分析。")

# ✅ 圖片辨識莊閒和位置
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

    return columns

# ✅ 生成副路資料
def generate_road(columns, offset):
    road = []
    for col in range(offset, len(columns)):
        current_col = columns[col]
        prev_col = columns[col - offset]
        if len(current_col) == len(prev_col):
            road.append("紅")
        else:
            road.append("藍")
    return road

def generate_all_roads(columns):
    return {
        "大眼仔": generate_road(columns, 1),
        "小路": generate_road(columns, 2),
        "蟑螂路": generate_road(columns, 3),
    }

# ✅ GPT 預測邏輯
def get_prediction_with_gpt(columns, roads):
    flat = [x for col in columns for x in col][-60:]  # 限制輸入長度
    input_sequence = " ".join(flat)

    road_text = "\n".join([f"{name}：{' '.join(road)}" for name, road in roads.items()])

    prompt = f"""
你是一位資深百家樂看路專家，請根據以下牌路資料進行預測：
主要牌路：
{input_sequence}

副路走勢：
{road_text}

請預測下一顆開出的是「莊」或「閒」，並提供：
1. ✅ 預測
2. 📊 勝率（莊幾%、閒幾%）
3. 🧠 統合分析（語意清晰且合理）

輸出格式如下：
✅ 預測：莊
📊 勝率：莊 52.3%、閒 47.7%
🧠 統合分析：根據連續性趨勢與副路偏紅，預測莊方延續。
"""

    try:
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ GPT 分析失敗：\n{e}"

# ✅ 處理圖片訊息
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 圖片已接收，開始分析...")

    photo_file = await update.message.photo[-1].get_file()
    image_bytes = await photo_file.download_as_bytearray()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_image:
        temp_image.write(image_bytes)
        temp_path = temp_image.name

    try:
        columns = analyze_baccarat_image(temp_path)
        roads = generate_all_roads(columns)
        gpt_reply = get_prediction_with_gpt(columns, roads)
        await update.message.reply_text(gpt_reply)

    except Exception as e:
        await update.message.reply_text(f"⚠️ 分析錯誤：{e}")

# ✅ 啟動 Telegram Bot Webhook
app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

app.run_webhook(
    listen="0.0.0.0",
    port=10000,
    webhook_url=WEBHOOK_URL
)
