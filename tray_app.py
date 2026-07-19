#!/usr/bin/env python3
"""NetMon 系統匣版 -- 給 Windows 用,雙擊執行(或打包成的 exe)後圖示出現在工作列。

用法:
    python tray_app.py

右鍵選單:
    開啟 Dashboard    -> 瀏覽器打開即時報表
    暫停/繼續監控     -> 切換是否自動檢查
    設定              -> 瀏覽器打開設定頁
    結束              -> 存一份 report.html 快照後關閉

打包成單一 exe (不用另外裝 Python,雙擊就能跑):
    pip install pyinstaller pystray pillow
    pyinstaller --onefile --windowed --name NetMon tray_app.py
    輸出在 dist/NetMon.exe
"""

import os
import sys
import threading
import time
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pystray
from PIL import Image, ImageDraw

from app import start_scheduler, build_server, load_config, save_config, PORT
from report import generate_report
from db import get_conn

STATUS_COLORS = {
    "up": (34, 197, 94),
    "down": (239, 68, 68),
    "degraded": (239, 68, 68),  # 舊資料相容
    "paused": (100, 116, 139),
    "unknown": (120, 120, 120),
}

STATUS_LABELS = {
    "up": "網路正常",
    "down": "網路異常",
    "degraded": "網路異常",
    "paused": "已暫停",
    "unknown": "尚無資料",
}


def make_icon_image(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((8, 8, 56, 56), fill=color)
    return img


def latest_status():
    cfg = load_config()
    if not cfg:
        return "unknown"
    if cfg.get("monitoring_paused"):
        return "paused"
    try:
        with get_conn(cfg["db_path"]) as conn:
            row = conn.execute("SELECT status FROM checks ORDER BY id DESC LIMIT 1").fetchone()
            return row[0] if row else "unknown"
    except Exception:
        return "unknown"


def status_watcher(icon):
    while True:
        status = latest_status()
        icon.icon = make_icon_image(STATUS_COLORS.get(status, STATUS_COLORS["unknown"]))
        icon.title = f"NetMon - {STATUS_LABELS.get(status, '尚無資料')}"
        time.sleep(5)


def open_dashboard(icon, item):
    webbrowser.open(f"http://127.0.0.1:{PORT}")


def open_settings(icon, item):
    webbrowser.open(f"http://127.0.0.1:{PORT}/settings")


def toggle_pause(icon, item):
    cfg = load_config()
    if cfg:
        save_config({"monitoring_paused": not cfg.get("monitoring_paused", False)})


def quit_app(icon, item):
    cfg = load_config()
    if cfg:
        try:
            generate_report(cfg)  # 關閉前存一份 snapshot
        except Exception:
            pass
    icon.stop()
    os._exit(0)


def main():
    start_scheduler()
    server = build_server()
    threading.Thread(target=server.serve_forever, daemon=True).start()

    icon = pystray.Icon(
        "netmon",
        make_icon_image(STATUS_COLORS["unknown"]),
        "NetMon - 啟動中",
        menu=pystray.Menu(
            pystray.MenuItem("開啟 Dashboard", open_dashboard, default=True),
            pystray.MenuItem("暫停/繼續監控", toggle_pause),
            pystray.MenuItem("設定", open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("結束", quit_app),
        )
    )

    threading.Thread(target=status_watcher, args=(icon,), daemon=True).start()

    # 第一次沒有設定檔:自動跳瀏覽器到設定精靈
    if not load_config():
        webbrowser.open(f"http://127.0.0.1:{PORT}/setup")

    icon.run()


if __name__ == "__main__":
    main()
