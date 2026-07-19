"""Core check/speedtest logic, shared by the CLI (main.py) and the
persistent web server (app.py)."""

import time

from checker import ping_host, check_http
from db import init_db, get_conn
from notifier import send_telegram

DEFAULTS = {
    # 路由器 IP -- 空字串代表尚未設定,強制在首次設定時填入
    "gateway_ip": "",
    "endpoints": [
        "https://www.google.com",
        "https://www.cloudflare.com",
        "https://www.microsoft.com",
    ],
    "ping_timeout": 3,
    "http_timeout": 5,
    "check_interval_sec": 60,

    # ═══ 異常判定條件 ═══
    # 前兩項強制啟用,無法關閉:
    #   1. 路由器 ping 不到   → 異常 (內部/LAN 問題)
    #   2. 對外連線全部失敗    → 異常 (對外/ISP 問題)
    # 下列三項是選用門檻,使用者可以自行 enable/disable + 調整數值:
    "anomaly_check_router_latency": True,
    "anomaly_router_latency_ms": 100,      # 路由器延遲 > 此值 → 異常
    "anomaly_check_download_speed": True,
    "anomaly_download_min_mbps": 50,        # 下載 < 此值 → 異常
    "anomaly_check_asymmetric": True,
    "anomaly_asymmetric_ratio": 0.5,        # 下載 < 上傳 × 此比例 → 異常 (不對稱)

    "db_path": "netmon.db",
    "report_path": "report.html",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "monitoring_paused": False,
}

LEGACY_FIELD_MAP = {
    # 舊欄位 → 新欄位;讓從舊版升級的 config.json 保留自訂數值
    "degraded_latency_ms": "anomaly_router_latency_ms",
    "speed_alert_threshold_mbps": "anomaly_download_min_mbps",
}


def with_defaults(cfg):
    merged = dict(DEFAULTS)
    if cfg:
        for old_key, new_key in LEGACY_FIELD_MAP.items():
            if old_key in cfg and new_key not in cfg:
                merged[new_key] = cfg[old_key]
        merged.update({k: v for k, v in cfg.items() if k not in LEGACY_FIELD_MAP})
    return merged


last_run_info = {"speedtest_error": None, "speedtest_attempted_ts": None}


def _get_recent_speedtest(db_path, max_age_sec=300):
    """回傳最近一次測速資料 (若在 max_age_sec 內);超過就當作沒有現況資料,
    避免用陳舊的數字誤判當下的網路狀態。"""
    now = int(time.time())
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT download_mbps, upload_mbps, ts FROM speedtests "
            "WHERE ts > ? ORDER BY ts DESC LIMIT 1",
            (now - max_age_sec,)
        ).fetchone()
    return row  # (download, upload, ts) or None


def _evaluate_anomaly(cfg, gw_ok, gw_latency, ext_ok, latest_speed):
    """檢查所有異常判定條件,回傳 (status, reason_list)。
    status 只有 "up" 或 "down" 兩種 -- 使用者要求把「延遲偏高」跟「異常」合併成
    一個事件類型,詳情放在 reason 裡描述。"""
    reasons = []

    # 這兩個永遠啟用,判斷邏輯無門檻
    if not gw_ok:
        reasons.append("路由器 ping 不到")
    if not ext_ok:
        reasons.append("對外連線全部失敗")

    # 選用門檻:延遲
    if (cfg["anomaly_check_router_latency"] and gw_ok
            and gw_latency is not None
            and gw_latency > cfg["anomaly_router_latency_ms"]):
        reasons.append(
            f"路由器延遲 {gw_latency:.0f}ms > {cfg['anomaly_router_latency_ms']}ms 門檻"
        )

    # 選用門檻:測速 (需要近期測速資料)
    if latest_speed:
        s_down, s_up, _ = latest_speed
        if (cfg["anomaly_check_download_speed"] and s_down is not None
                and s_down < cfg["anomaly_download_min_mbps"]):
            reasons.append(
                f"下載 {s_down} Mbps < {cfg['anomaly_download_min_mbps']} Mbps 門檻"
            )
        if (cfg["anomaly_check_asymmetric"] and s_down is not None
                and s_up is not None and s_up > 1
                and s_down < s_up * cfg["anomaly_asymmetric_ratio"]):
            reasons.append(
                f"下載 {s_down} 明顯低於上傳 {s_up} Mbps (低於 {cfg['anomaly_asymmetric_ratio']:.0%})"
            )

    status = "down" if reasons else "up"
    return status, reasons


def run_check(cfg):
    cfg = with_defaults(cfg)
    db_path = cfg["db_path"]
    init_db(db_path)

    if cfg["gateway_ip"]:
        gw_ok, gw_latency = ping_host(cfg["gateway_ip"], cfg["ping_timeout"])
    else:
        gw_ok, gw_latency = False, None  # 未設定 gateway 直接視為不通

    ext_results = [check_http(url, cfg["http_timeout"]) for url in cfg["endpoints"]]
    ext_ok = any(ok for ok, _ in ext_results)
    ext_latencies = [l for ok, l in ext_results if ok and l is not None]
    ext_latency = sum(ext_latencies) / len(ext_latencies) if ext_latencies else None

    latest_speed = _get_recent_speedtest(db_path)
    status, reasons = _evaluate_anomaly(cfg, gw_ok, gw_latency, ext_ok, latest_speed)
    reason_str = " · ".join(reasons) if reasons else ""

    now = int(time.time())

    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO checks (ts, gateway_ok, gateway_latency, external_ok, external_latency, status, reason) "
            "VALUES (?,?,?,?,?,?,?)",
            (now, int(gw_ok), gw_latency, int(ext_ok), ext_latency, status, reason_str)
        )

        prev_row = conn.execute(
            "SELECT status FROM checks WHERE id != (SELECT MAX(id) FROM checks) ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_status = prev_row[0] if prev_row else "up"

        open_outage = conn.execute(
            "SELECT id, start_ts FROM outages WHERE end_ts IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()

        token, chat_id = cfg["telegram_bot_token"], cfg["telegram_chat_id"]

        if status == "down" and prev_status != "down":
            conn.execute(
                "INSERT INTO outages (start_ts, type, reason) VALUES (?, ?, ?)",
                (now, "anomaly", reason_str)
            )
            send_telegram(
                token, chat_id,
                f"🔴 網路異常\n原因: {reason_str}\n時間: {time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        elif status != "down" and prev_status == "down" and open_outage:
            oid, start_ts = open_outage
            duration = now - start_ts
            conn.execute(
                "UPDATE outages SET end_ts=?, duration_sec=? WHERE id=?",
                (now, duration, oid)
            )
            send_telegram(
                token, chat_id,
                f"🟢 網路恢復\n中斷時長: {duration // 60}分{duration % 60}秒"
            )

    return status


def run_speedtest(cfg):
    """用 Cloudflare 的公開 speedtest endpoint 測速。告警邏輯不再放在這裡 --
    現在統一由 run_check 綜合評估後發送 (避免同一個異常重複推播)。"""
    cfg = with_defaults(cfg)
    db_path = cfg["db_path"]
    init_db(db_path)

    last_run_info["speedtest_attempted_ts"] = int(time.time())
    down = up = ping = None
    try:
        import urllib.request
        import ssl

        ctx = ssl.create_default_context()
        headers = {"User-Agent": "NetMon/1.0"}

        ping_start = time.time()
        req = urllib.request.Request(
            "https://speed.cloudflare.com/__down?bytes=0", headers=headers
        )
        with urllib.request.urlopen(req, timeout=5, context=ctx) as r:
            r.read()
        ping = round((time.time() - ping_start) * 1000, 1)

        down_bytes = 25_000_000
        req = urllib.request.Request(
            f"https://speed.cloudflare.com/__down?bytes={down_bytes}", headers=headers
        )
        received = 0
        start = time.time()
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                received += len(chunk)
        elapsed = time.time() - start
        if elapsed > 0 and received > 0:
            down = round((received * 8 / 1_000_000) / elapsed, 2)

        up_bytes = 10_000_000
        upload_data = b"\x00" * up_bytes
        req = urllib.request.Request(
            "https://speed.cloudflare.com/__up",
            data=upload_data, method="POST",
            headers={"Content-Type": "application/octet-stream", **headers},
        )
        start = time.time()
        with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
            r.read()
        elapsed = time.time() - start
        if elapsed > 0:
            up = round((up_bytes * 8 / 1_000_000) / elapsed, 2)

        last_run_info["speedtest_error"] = None
    except Exception as e:
        last_run_info["speedtest_error"] = f"{type(e).__name__}: {e}"
        return None, None, None

    now = int(time.time())
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO speedtests (ts, download_mbps, upload_mbps, ping_ms) VALUES (?,?,?,?)",
            (now, down, up, ping)
        )

    return down, up, ping
