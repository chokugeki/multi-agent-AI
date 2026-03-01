@echo off
title Sato Digital Clone CLI

echo ========================================================
echo  Sato Digital Clone CLI の起動を準備しています...
echo ========================================================

wsl --cd /home/toshiaki/sato-clone-org -e bash -c "source .venv/bin/activate && exec python3 infrastructure/local_cli.py"

pause
