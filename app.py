import logging
import os
import re
import sys
import time
import traceback

import requests

LOG_FILE_PATH = r"C:\WebAccess\Node\BwMobileApp.Log"
#LOG_FILE_PATH = r"C:\Users\user\Documents\GayHub\a.log"

# 相對路徑以程式所在資料夾為準，避免從排程器 / 捷徑啟動時工作目錄不同而找不到 user.txt
# 打包成 exe 時 __file__ 會指向暫存解壓目錄，要改用 exe 本身的位置
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USER_FILE_PATH = os.path.join(BASE_DIR, "user.txt")
APP_LOG_PATH = os.path.join(BASE_DIR, "line-resend.log")

LINE_API_URL = "https://api.line.me/v2/bot/message/push"

POLL_INTERVAL = 0.5     # 秒，檢查 log 檔的間隔
HTTP_TIMEOUT = 15       # 秒，LINE API 逾時
HTTP_RETRIES = 3        # 網路錯誤重試次數
RESTART_DELAY = 5       # 秒，發生未預期錯誤後重新開始前的等待

# 同時輸出到畫面與 line-resend.log，視窗被關掉也能事後查原因
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(APP_LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("line-resend")

header_pattern = re.compile(r'\[Debug\]Header - Bearer (.+)')
message_pattern = re.compile(r'\[Debug\]message - (.+)')


# 讀取 user.txt 內的所有 User ID
def read_user_ids():
    with open(USER_FILE_PATH, 'r', encoding='utf-8-sig') as f:
        return [line.strip() for line in f if line.strip()]


# 發送訊息，token 每次傳進來；網路錯誤會重試，不會讓程式結束
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
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            response = requests.post(LINE_API_URL, headers=headers, json=body, timeout=HTTP_TIMEOUT)
        except requests.RequestException as e:
            log.warning("傳送失敗（第 %d/%d 次）: %s", attempt, HTTP_RETRIES, e)
            if attempt < HTTP_RETRIES:
                time.sleep(2 * attempt)
            continue
        if response.status_code == 200:
            return True
        log.error("傳送失敗: %s %s", response.status_code, response.text)
        # 5xx / 429 才值得重試；4xx（例如 token 過期 401）重試也沒用
        if (response.status_code >= 500 or response.status_code == 429) and attempt < HTTP_RETRIES:
            time.sleep(2 * attempt)
            continue
        return False
    return False


# log 可能是 UTF-8，也可能是 Windows 中文系統的 cp950（Big5），都解不了就用替代字元，不要讓程式掛掉
def decode_line(raw):
    try:
        return raw.decode('utf-8')
    except UnicodeDecodeError:
        try:
            return raw.decode('cp950')
        except UnicodeDecodeError:
            return raw.decode('utf-8', errors='replace')


def handle_line(line, state):
    line = line.strip()

    # 如果是 Header
    header_match = header_pattern.search(line)
    if header_match:
        state['token'] = header_match.group(1).strip()
        log.info("更新 token：%s...", state['token'][:10])

    # 如果是 Message
    message_match = message_pattern.search(line)
    if message_match and state['token']:
        message = message_match.group(1)
        user_ids = read_user_ids()
        ok = sum(1 for user_id in user_ids if send_line_message(user_id, message, state['token']))
        if ok == len(user_ids):
            log.info("推送訊息：%s", message)
        else:
            log.error("推送訊息部分失敗（成功 %d/%d）：%s", ok, len(user_ids), message)


def watch_log(state):
    """
    每次輪詢都重新開檔、讀完就關檔：
    - 不長時間占用 log 檔，原系統要輪替 / 刪除 log 時不會被擋住
    - log 被清空或換成新檔（大小比上次讀到的位置小）時，從頭開始讀
    - 只處理已寫完（有換行結尾）的整行，避免讀到寫一半的內容
    """
    pos = state.get('pos')
    if pos is None:
        pos = os.path.getsize(LOG_FILE_PATH)  # 第一次啟動：從檔案尾開始
    pending = b''

    while True:
        try:
            size = os.path.getsize(LOG_FILE_PATH)
        except OSError:
            # 檔案暫時不存在（輪替中），等它回來
            time.sleep(POLL_INTERVAL)
            continue

        if size < pos:
            log.info("偵測到 log 檔被清空或更換，從頭開始讀取")
            pos = 0
            pending = b''

        if size > pos:
            with open(LOG_FILE_PATH, 'rb') as f:
                f.seek(pos)
                chunk = f.read(size - pos)
            pos += len(chunk)
            pending += chunk
            *lines, pending = pending.split(b'\n')
            line_start = pos - len(pending) - sum(len(raw) + 1 for raw in lines)
            for raw in lines:
                state['pos'] = line_start  # 這行出錯重啟時，從這行重新處理，不重送前面已處理的
                handle_line(decode_line(raw), state)
                line_start += len(raw) + 1
                state['pos'] = line_start
        else:
            time.sleep(POLL_INTERVAL)


def main():
    log.info("開始監控 log 檔：%s", LOG_FILE_PATH)
    state = {'token': None, 'pos': None}
    # 任何未預期的錯誤都記錄下來並自動重新開始，而不是讓視窗直接關掉
    while True:
        try:
            watch_log(state)
        except KeyboardInterrupt:
            log.info("手動停止")
            break
        except Exception:
            log.error("發生未預期錯誤，%d 秒後重新開始：\n%s", RESTART_DELAY, traceback.format_exc())
            time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    main()
