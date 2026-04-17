"""
Telegram Bot - /report 명령어 수신 시 스크리닝 실행
실행: python3 bot.py
"""

import time
import requests
import subprocess
import sys
import os

BOT_TOKEN = "8654658267:AAEWsIE8MbM-V_9mR77LIymdfsb_cEDFJug"
BASE_URL  = f"https://api.telegram.org/bot{BOT_TOKEN}"
BASE_DIR  = os.path.dirname(os.path.abspath(__file__))


def get_updates(offset=None):
    params = {"timeout": 30, "allowed_updates": ["message"]}
    if offset:
        params["offset"] = offset
    try:
        r = requests.get(f"{BASE_URL}/getUpdates", params=params, timeout=35)
        return r.json().get("result", [])
    except Exception as e:
        print(f"[getUpdates 오류] {e}")
        return []


def send_message(chat_id, text):
    try:
        requests.post(
            f"{BASE_URL}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=15,
        )
    except Exception as e:
        print(f"[sendMessage 오류] {e}")


def run_screening(chat_id):
    send_message(chat_id, "스크리닝 시작 중... 잠시 기다려 주세요 ⏳")
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(BASE_DIR, "screening.py")],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            send_message(chat_id, "스크리닝 완료 ✅\n리포트와 분석이 전송되었습니다.")
        else:
            err = (result.stderr or result.stdout)[-500:]
            send_message(chat_id, f"스크리닝 오류 ❌\n{err}")
    except subprocess.TimeoutExpired:
        send_message(chat_id, "타임아웃 오류: 스크리닝이 5분을 초과했습니다.")
    except Exception as e:
        send_message(chat_id, f"실행 오류: {e}")


def main():
    print("[bot] 텔레그램 봇 시작 - /report 명령어 대기 중...")
    offset = None
    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            chat_id = msg.get("chat", {}).get("id")
            if not chat_id:
                continue
            if text == "/report" or text.startswith("/report@"):
                print(f"[bot] /report 요청 수신 (chat_id={chat_id})")
                run_screening(chat_id)
            elif text == "/start":
                send_message(chat_id, "안녕하세요! /report 를 입력하면 미국 주식 스크리닝 리포트를 생성합니다.")
        time.sleep(1)


if __name__ == "__main__":
    main()
