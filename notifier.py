import urllib.request
import urllib.parse


def send_telegram(token, chat_id, text):
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        urllib.request.urlopen(url, data=data, timeout=10)
        return True
    except Exception:
        return False
