#!/usr/bin/env python3
"""NetMon 常駐服務(headless版)"""

import json
import os
import socket
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import run_check, run_speedtest, with_defaults, DEFAULTS
from checker import detect_gateway as _detect_gateway
from notifier import send_telegram
from report import render_html

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
PORT = 8787

_cfg_lock = threading.Lock()
scheduler_state = {"last_tick": None, "last_error": None}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return with_defaults(json.load(f))


def save_config(updates):
    with _cfg_lock:
        current = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, encoding="utf-8") as f:
                current = json.load(f)
        current.update(updates)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False, indent=2)
    from db import init_db
    init_db(with_defaults(current)["db_path"])


def detect_gateway():
    """回傳自動偵測到的 gateway IP,失敗回傳空字串 (不再用寫死的預設值)。"""
    return _detect_gateway() or ""


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def scheduler_loop():
    while True:
        try:
            scheduler_state["last_tick"] = time.time()
            cfg = load_config()
            if not cfg:
                time.sleep(5)
                continue

            if cfg.get("monitoring_paused"):
                time.sleep(min(cfg.get("check_interval_sec", 60), 10))
                continue

            # 先跑測速,再跑檢查 (讓 check 能拿到最新測速資料判斷異常)
            try:
                run_speedtest(cfg)
            except Exception as e:
                scheduler_state["last_error"] = f"speedtest: {e}"
                print(f"[scheduler] speedtest error: {e}")

            try:
                run_check(cfg)
            except Exception as e:
                scheduler_state["last_error"] = f"check: {e}"
                print(f"[scheduler] check error: {e}")

            time.sleep(max(cfg["check_interval_sec"], 5))
        except Exception as e:
            scheduler_state["last_error"] = str(e)
            print(f"[scheduler] unexpected error, retrying in 10s: {e}")
            traceback.print_exc()
            time.sleep(10)


SETTINGS_FORM = """<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, "PingFang TC", "Microsoft JhengHei", sans-serif; background:#0f1117; color:#e6e6e6; margin:0; padding:24px; }}
.card {{ background:#1a1d27; border-radius:12px; padding:24px; max-width:560px; margin:0 auto; }}
label {{ display:block; margin-top:16px; font-size:14px; color:#ccc; }}
input[type=text], input[type=number], input[type=password] {{ width:100%; box-sizing:border-box; padding:10px; margin-top:6px; border-radius:8px; border:1px solid #333; background:#0f1117; color:#eee; font-size:15px; }}
input[type=checkbox] {{ margin-right:8px; transform: scale(1.2); vertical-align:middle; }}
.hint {{ color:#777; font-size:12px; margin-top:4px; }}
.section {{ margin-top:28px; padding-top:20px; border-top:1px solid #2a2d3a; }}
.section h3 {{ font-size:15px; color:#aaa; margin:0 0 4px 0; }}
.section-desc {{ color:#777; font-size:12px; margin-bottom:8px; }}
.cond {{ background:#0f1117; padding:12px; border-radius:8px; margin-top:10px; }}
.cond-inline {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; font-size:14px; color:#ccc; }}
.cond-inline input[type=number] {{ width:90px; margin:0; padding:6px; }}
.cond-fixed {{ background:#1f2028; padding:10px 12px; border-radius:8px; margin-top:8px; font-size:14px; color:#aaa; }}
.cond-fixed b {{ color:#4ade80; }}
button {{ margin-top:24px; width:100%; padding:12px; border:none; border-radius:8px; background:#4ade80; color:#0f1117; font-weight:bold; font-size:15px; cursor:pointer; }}
.secondary-btn {{ margin-top:10px; background:#242836; color:#ccc; }}
h1 {{ font-size:19px; }}
a {{ color:#60a5fa; }}
#test-result {{ font-size:13px; margin-top:8px; min-height:16px; }}
</style>
</head>
<body>
<div class="card">
<h1>{title}</h1>
<p style="color:#999; font-size:14px;">{intro}</p>
<form method="POST" action="{action}">

  <label>路由器 IP (gateway)
    <input type="text" name="gateway_ip" value="{gateway_ip}" required>
  </label>
  <div class="hint">用來判斷是路由器/LAN問題還是對外斷線。上方預設值是自動偵測到的,可以自行修改。</div>

  <label>檢查頻率(秒)
    <input type="number" name="check_interval_sec" value="{check_interval_sec}" min="10" required>
  </label>
  <div class="hint">每次都會做「連線檢查+測速」。太短會持續消耗頻寬,建議 60 秒以上。</div>

  <div class="section">
    <h3>異常判定條件</h3>
    <div class="section-desc">符合下列任一條件就會被判定為「網路異常」,並在 Telegram 推播通知(若有設定)。</div>

    <div class="cond-fixed">
      <b>✓ 一定會偵測</b> · 路由器 ping 不到 → 異常 (內部/LAN 問題)
    </div>
    <div class="cond-fixed">
      <b>✓ 一定會偵測</b> · 所有對外連線都失敗 → 異常 (對外/ISP 問題)
    </div>

    <div class="cond">
      <label style="margin:0;">
        <input type="checkbox" name="anomaly_check_router_latency" {rl_checked}>
        <span class="cond-inline">路由器延遲 &gt;
          <input type="number" name="anomaly_router_latency_ms" value="{anomaly_router_latency_ms}" min="1">
          ms 時視為異常
        </span>
      </label>
    </div>

    <div class="cond">
      <label style="margin:0;">
        <input type="checkbox" name="anomaly_check_download_speed" {ds_checked}>
        <span class="cond-inline">下載速度 &lt;
          <input type="number" name="anomaly_download_min_mbps" value="{anomaly_download_min_mbps}" min="1" step="0.1">
          Mbps 時視為異常
        </span>
      </label>
    </div>

    <div class="cond">
      <label style="margin:0;">
        <input type="checkbox" name="anomaly_check_asymmetric" {as_checked}>
        <span class="cond-inline">下載 &lt; 上傳 ×
          <input type="number" name="anomaly_asymmetric_ratio" value="{anomaly_asymmetric_ratio}" min="0.1" max="1" step="0.05">
          時視為異常 (偵測下載明顯低於上傳的不對稱情況)
        </span>
      </label>
    </div>
  </div>

  <div class="section">
    <h3>Telegram 通知(選填)</h3>
    <div class="section-desc">網路異常/恢復時透過 Telegram Bot 推播。留空則不推播。</div>

    <label>Telegram Bot Token
      <input type="text" name="telegram_bot_token" id="tg_token" value="{telegram_bot_token}" placeholder="123456:ABC-...">
    </label>

    <label>Telegram Chat ID
      <input type="text" name="telegram_chat_id" id="tg_chat" value="{telegram_chat_id}" placeholder="例如 123456789">
    </label>

    <button type="button" class="secondary-btn" onclick="testTelegram()">測試 Telegram 通知</button>
    <div id="test-result"></div>
  </div>

  <button type="submit">{button_label}</button>
</form>
{back_link}
</div>
<script>
function testTelegram() {{
  var el = document.getElementById('test-result');
  el.textContent = '傳送中...';
  fetch('/api/test-telegram', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
    body: 'token=' + encodeURIComponent(document.getElementById('tg_token').value) +
          '&chat_id=' + encodeURIComponent(document.getElementById('tg_chat').value)
  }}).then(function(r) {{
    if (r.status === 200) {{ el.textContent = '已送出,請檢查 Telegram'; el.style.color = '#4ade80'; }}
    else {{ el.textContent = '失敗,請確認 Token/Chat ID(或尚未填寫)'; el.style.color = '#ef4444'; }}
  }}).catch(function() {{
    el.textContent = '發送失敗'; el.style.color = '#ef4444';
  }});
}}
</script>
</body>
</html>
"""


def _render_settings(cfg, is_setup):
    """cfg 可能是 None (setup 情境) 或現有設定。"""
    if is_setup:
        gateway_default = detect_gateway()  # 空字串就空字串,由使用者填入
        title = "第一次設定 NetMon"
        intro = ("填好按下面按鈕就會開始監控。路由器 IP 已幫你自動偵測 -- 沒偵測到的話請自行輸入,"
                 "在命令提示字元打 ipconfig 查「預設閘道」。")
        action = "/setup"
        button_label = "開始監控"
        back_link = ""
        c = with_defaults({"gateway_ip": gateway_default})
    else:
        title = "設定"
        intro = "修改後按儲存,背景排程會在下一輪自動套用新設定。"
        action = "/settings"
        button_label = "儲存"
        back_link = '<p><a href="/">← 回 Dashboard</a></p>'
        c = cfg or with_defaults({})

    return SETTINGS_FORM.format(
        title=title, intro=intro, action=action, button_label=button_label, back_link=back_link,
        gateway_ip=c["gateway_ip"],
        check_interval_sec=c["check_interval_sec"],
        anomaly_router_latency_ms=c["anomaly_router_latency_ms"],
        rl_checked="checked" if c["anomaly_check_router_latency"] else "",
        anomaly_download_min_mbps=c["anomaly_download_min_mbps"],
        ds_checked="checked" if c["anomaly_check_download_speed"] else "",
        anomaly_asymmetric_ratio=c["anomaly_asymmetric_ratio"],
        as_checked="checked" if c["anomaly_check_asymmetric"] else "",
        telegram_bot_token=c["telegram_bot_token"],
        telegram_chat_id=c["telegram_chat_id"],
    )


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send_html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, path):
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def do_GET(self):
        cfg = load_config()
        if self.path == "/" or self.path == "":
            if not cfg:
                return self._redirect("/setup")
            return self._send_html(render_html(cfg, app_mode=True, scheduler_state=scheduler_state))

        if self.path == "/setup":
            if cfg:
                return self._redirect("/")
            return self._send_html(_render_settings(None, is_setup=True))

        if self.path == "/settings":
            return self._send_html(_render_settings(cfg, is_setup=False))

        if self.path == "/api/download-report":
            # 產生 clean snapshot (不含即時按鈕、不 auto refresh),直接下載
            cfg = cfg or with_defaults({})
            html = render_html(cfg, app_mode=False, scheduler_state=None)
            body = html.encode("utf-8")
            filename = time.strftime("netmon-report-%Y%m%d-%H%M%S.html")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        self._send_html("<h1>404</h1>", status=404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        fields = urllib.parse.parse_qs(body)

        def get(name, default=""):
            return fields.get(name, [default])[0]

        if self.path in ("/setup", "/settings"):
            gateway_ip = get("gateway_ip", "").strip()
            if not gateway_ip:
                # 空的不讓儲存,回設定頁重來
                cfg = load_config()
                is_setup = (self.path == "/setup")
                return self._send_html(_render_settings(cfg, is_setup=is_setup))

            save_config({
                "gateway_ip": gateway_ip,
                "telegram_bot_token": get("telegram_bot_token", ""),
                "telegram_chat_id": get("telegram_chat_id", ""),
                "check_interval_sec": int(float(get("check_interval_sec") or DEFAULTS["check_interval_sec"])),
                "anomaly_check_router_latency": "anomaly_check_router_latency" in fields,
                "anomaly_router_latency_ms": float(get("anomaly_router_latency_ms") or DEFAULTS["anomaly_router_latency_ms"]),
                "anomaly_check_download_speed": "anomaly_check_download_speed" in fields,
                "anomaly_download_min_mbps": float(get("anomaly_download_min_mbps") or DEFAULTS["anomaly_download_min_mbps"]),
                "anomaly_check_asymmetric": "anomaly_check_asymmetric" in fields,
                "anomaly_asymmetric_ratio": float(get("anomaly_asymmetric_ratio") or DEFAULTS["anomaly_asymmetric_ratio"]),
            })
            return self._redirect("/")

        if self.path == "/api/toggle-pause":
            cfg = load_config() or with_defaults({})
            new_state = not cfg.get("monitoring_paused", False)
            save_config({"monitoring_paused": new_state})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"paused" if new_state else b"running")
            return

        if self.path == "/api/test-telegram":
            token = get("token", "")
            chat_id = get("chat_id", "")
            ok = send_telegram(token, chat_id, "🔔 NetMon 測試訊息 -- 收到這則代表 Telegram 設定正確")
            self.send_response(200 if ok else 400)
            self.end_headers()
            return

        self._send_html("<h1>404</h1>", status=404)


def start_scheduler():
    threading.Thread(target=scheduler_loop, daemon=True).start()


def build_server():
    return ThreadingHTTPServer(("0.0.0.0", PORT), Handler)


if __name__ == "__main__":
    start_scheduler()
    server = build_server()
    print("NetMon 已啟動")
    print(f"  本機瀏覽器打開: http://127.0.0.1:{PORT}")
    print(f"  同網段其他裝置打開: http://{lan_ip()}:{PORT}")
    server.serve_forever()
