#!/bin/bash
# sato_patrol_trigger.sh
# このスクリプトはcronで定期実行され、Sato Cloneの自律的パトロールを起動します。

# MQTTブローカーのアドレス（ローカルのDockerコンテナ）
MQTT_BROKER="localhost"
MQTT_PORT=1883
TOPIC="sato/pipeline/patrol/trigger"

# 今日の日付を取得
TODAY=$(date +"%Y-%m-%d")

# PublishするJSONペイロード
# 調査部に行わせる検索のテーマを指定します
PAYLOAD="{\"date\": \"$TODAY\", \"query\": \"最新のAIエージェント、軽量LLM、AGIに関するニュース\", \"action\": \"start_patrol\"}"

echo "Starting Proactive Patrol trigger for $TODAY..."

# mosquitto_pubコマンドでメッセージを投下（Docker内を叩くか、ホストにインストールされたクライアントを使う）
# docker exec -it sato-mqtt-broker mosquitto_pub -h localhost -p 1883 -t "$TOPIC" -m "$PAYLOAD"
mosquitto_pub -h $MQTT_BROKER -p $MQTT_PORT -t "$TOPIC" -m "$PAYLOAD"

if [ $? -eq 0 ]; then
  echo "Patrol trigger published successfully."
else
  echo "Failed to publish patrol trigger. Ensure mosquitto_pub is installed."
fi
