import time
import requests
import re

#LOG_FILE_PATH = r"C:\WebAccess\Node\BwMobileApp.Log"
LOG_FILE_PATH = r"C:\Users\user\Documents\GayHub\a.log"
USER_FILE_PATH = r"user.txt"

LINE_API_URL = "https://api.line.me/v2/bot/message/push"

# 讀取 user.txt 內的所有 User ID
def read_user_ids():
    with open(USER_FILE_PATH, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]

# 發送訊息，這次 token 是每次傳進來
def send_line_message(user_id, message, access_token):
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    body = {
        "to": user_id,
        "messages": [
            {
                "type": "text",
                "text": message
            }
        ]
    }
    response = requests.post(LINE_API_URL, headers=headers, json=body)
    if response.status_code != 200:
        print(f"傳送失敗: {response.status_code} {response.text}")

def watch_log():
    print("開始監控 log 檔...")
    token = None
    header_pattern = re.compile(r'\[Debug\]Header - Bearer (.+)')
    message_pattern = re.compile(r'\[Debug\]message - (.+)')
    
    with open(LOG_FILE_PATH, 'r', encoding='utf-8') as f:
        f.seek(0, 2)  # 移到檔案尾
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.5)
                continue
            line = line.strip()

            # 如果是 Header
            header_match = header_pattern.search(line)
            if header_match:
                token = header_match.group(1)
                print(f"更新 token：{token[:10]}...")  # 前10個字看一下 debug

            # 如果是 Message
            message_match = message_pattern.search(line)
            if message_match and token:
                message = message_match.group(1)
                user_ids = read_user_ids()
                for user_id in user_ids:
                    send_line_message(user_id, message, token)
                print(f"推送訊息：{message}")

if __name__ == "__main__":
    watch_log()
