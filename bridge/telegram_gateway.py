import os
import asyncio
import logging
import paho.mqtt.client as mqtt
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

load_dotenv(dotenv_path="/app/config/global.env")

# 設定
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MQTT_HOST = "mqtt-broker"
MQTT_PORT = 1883
USER_CHAT_ID = int(os.getenv("TELEGRAM_USER_ID")) # Sato氏のIDに限定

# MQTT設定
mqtt_client = mqtt.Client()

def on_connect(client, userdata, flags, rc):
    print(f"Connected to MQTT Broker with result code {rc}")
    client.subscribe("sato/report/ceo") # 組織からの報告を購読

def on_message(client, userdata, msg):
    # 組織からのメッセージをTelegramへ転送
    text = msg.payload.decode()
    asyncio.run_coroutine_threadsafe(
        bot_app.bot.send_message(chat_id=USER_CHAT_ID, text=text),
        loop
    )

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# Telegramハンドラ
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != USER_CHAT_ID:
        return # 指定ユーザー以外は無視

    # ユーザーのメッセージをMQTTへPublish
    user_text = update.message.text
    mqtt_client.publish("sato/command/external", user_text)

# メイン実行部
if __name__ == '__main__':
    mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
    mqtt_client.loop_start()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    bot_app = ApplicationBuilder().token(TOKEN).build()
    bot_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_user_message))
    
    print("Telegram Gateway is running...")
    bot_app.run_polling()