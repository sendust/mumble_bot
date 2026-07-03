#!/bin/bash

# Ctrl+C(SIGINT)나 종료 시그널(SIGTERM)을 받으면 루프를 깨고 종료하도록 설정
trap "echo -e '\n[INFO] Script interrupted by user. Exiting...'; exit 0" SIGINT SIGTERM

echo "[INFO] Starting Mumble bot loop..."

while true; do
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting get_mumble.py..."
    
    # 가상환경 내부라면 가상환경의 파이썬 경로를 명시해주는 것이 좋습니다.
    # 예: /home/sendust/mumble/.venv/bin/python3
    /home/sendust/mumblebot/bin/python3 mbot.py config.json
    
    # 프로그램이 종료된 후의 종료 코드(Exit Code) 확인
    EXIT_CODE=$?
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] mbot.py exited with code $EXIT_CODE."
    
    echo "[INFO] Waiting 10 seconds before restarting..."
    echo "--------------------------------------------------"
    
    # 10초 동안 대기
    sleep 10
done
