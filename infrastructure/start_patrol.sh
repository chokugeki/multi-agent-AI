#!/bin/bash
# start_patrol.sh: 背景で自律パトロールを起動・常駐させるスクリプト

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
cd "$DIR/.."

# 既に動いている場合は何もしない
if pgrep -f "patrol.py$" > /dev/null; then
    echo "patrol.py is already running."
    exit 0
fi

echo "Starting patrol.py in background..."
nohup python3 core/patrol.py > patrol.log 2>&1 &
echo "Started with PID $!"
echo "Log: patrol.log"
