import sqlite3
import json
import time
from db import get_conn
from engine import last_run_info


def render_html(cfg, app_mode=False, scheduler_state=None):
    """
    app_mode=True  → 即時 Dashboard,含 nav bar、下載報表按鈕、auto refresh、倒數計時
    app_mode=False → 靜態 snapshot,純資料,適合下載存檔或當作 ISP 申訴附件
    """
    db_path = cfg["db_path"]
    paused = bool(cfg.get("monitoring_paused", False))
    check_interval = cfg.get("check_interval_sec", 60)

    with get_conn(db_path) as conn:
        conn.row_factory = sqlite3.Row
        checks = conn.execute(
            "SELECT ts, status, gateway_latency, external_latency, reason FROM checks ORDER BY ts ASC"
        ).fetchall()
        outages = conn.execute(
            "SELECT start_ts, end_ts, duration_sec, type, reason FROM outages ORDER BY start_ts DESC"
        ).fetchall()
        speedtests = conn.execute(
            "SELECT ts, download_mbps, upload_mbps, ping_ms FROM speedtests ORDER BY ts ASC"
        ).fetchall()

    total = len(checks)
    up_count = sum(1 for c in checks if c["status"] == "up")
    uptime_pct = round(up_count / total * 100, 2) if total else 100.0

    latest = checks[-1] if checks else None
    latest_status = latest["status"] if latest else "unknown"
    latest_ts = latest["ts"] if latest else None
    latest_gw_latency = latest["gateway_latency"] if latest else None
    latest_ext_latency = latest["external_latency"] if latest else None
    latest_reason = latest["reason"] if latest else None
    latest_speed = speedtests[-1] if speedtests else None

    # 狀態簡化:只剩 up / down / unknown。「延遲偏高」不再是獨立狀態,
    # 現在會併入 down 並在 reason 說明。
    status_map = {
        "up": ("#22c55e", "🟢 正常"),
        "down": ("#ef4444", "🔴 異常"),
        "degraded": ("#ef4444", "🔴 異常"),  # 舊資料相容,現在都算異常
        "unknown": ("#666", "⚪ 尚無資料"),
    }
    status_color, status_label = status_map.get(latest_status, status_map["unknown"])
    monitor_color, monitor_label = ("#888", "⏸ 監控已暫停") if paused else ("#22c55e", "🟢 監控中")

    latest_time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest_ts)) if latest_ts else "尚無資料"

    gw_str = f'{latest_gw_latency:.0f}ms' if latest_gw_latency is not None else '-'
    ext_str = f'{latest_ext_latency:.0f}ms' if latest_ext_latency is not None else '-'
    down_str = f'{latest_speed["download_mbps"]:.1f}Mbps' if latest_speed and latest_speed["download_mbps"] is not None else '-'
    up_str = f'{latest_speed["upload_mbps"]:.1f}Mbps' if latest_speed and latest_speed["upload_mbps"] is not None else '-'
    data_line = f"路由器延遲 {gw_str} · 對外延遲 {ext_str} · 下載 {down_str} · 上傳 {up_str}"

    # 異常時把原因秀在資料下面
    reason_line = ""
    if latest_status == "down" and latest_reason:
        reason_line = f'<div class="detail-line reason-line">異常原因: {latest_reason}</div>'

    speedtest_error_note = ""
    if app_mode and last_run_info.get("speedtest_error"):
        attempted_ts = last_run_info.get("speedtest_attempted_ts") or 0
        last_success_ts = latest_speed["ts"] if latest_speed else 0
        if attempted_ts > last_success_ts:
            speedtest_error_note = f" · ⚠️ 上次測速失敗: {last_run_info['speedtest_error']}"

    now = int(time.time())
    day_ago, week_ago = now - 86400, now - 7 * 86400
    checks_24h = [c for c in checks if c["ts"] >= day_ago]
    checks_7d = [c for c in checks if c["ts"] >= week_ago]
    uptime_24h = round(sum(1 for c in checks_24h if c["status"] == "up") / len(checks_24h) * 100, 2) if checks_24h else 100.0
    uptime_7d = round(sum(1 for c in checks_7d if c["status"] == "up") / len(checks_7d) * 100, 2) if checks_7d else 100.0

    schedule_line = ""
    next_check_ts = None
    if app_mode:
        if paused:
            schedule_line = "不會自動檢查"
        elif latest_ts:
            schedule_line = f"每 {check_interval} 秒自動檢查一次"
            next_check_ts = latest_ts + check_interval
            remaining = max(0, next_check_ts - int(time.time()))
            if remaining > 0:
                m, s = divmod(remaining, 60)
                initial = f"{m}分{s}秒" if m > 0 else f"{s}秒"
            else:
                initial = "即將檢查..."
            schedule_line += f" · 下次檢查倒數 <span id=\"countdown\">{initial}</span>"
        else:
            schedule_line = "監控已啟動,即將進行首次檢查..."
        if scheduler_state and scheduler_state.get("last_error"):
            schedule_line += f" · ⚠️ 背景執行緒最近一次錯誤: {scheduler_state['last_error']}"
        schedule_line += speedtest_error_note

    stats_html = ""
    if total > 0:
        stat_cards = [
            (f"{uptime_pct}%", "總可用率"),
            (f"{uptime_24h}%" if checks_24h else "-", "近24小時"),
            (f"{uptime_7d}%" if checks_7d else "-", "近7天"),
            (str(len(outages)), "總斷線次數"),
        ]
        stats_html = '<div class="stats" style="flex:2;">'
        for value, label in stat_cards:
            stats_html += f'<div class="stat"><div class="value">{value}</div><div class="label">{label}</div></div>'
        stats_html += '</div>'

    recent_checks = checks[-200:]
    latency_labels = [time.strftime("%m/%d %H:%M", time.localtime(c["ts"])) for c in recent_checks]
    latency_gw = [c["gateway_latency"] for c in recent_checks]
    latency_ext = [c["external_latency"] for c in recent_checks]

    recent_speed = speedtests[-100:]
    speed_labels = [time.strftime("%m/%d %H:%M", time.localtime(s["ts"])) for s in recent_speed]
    speed_down = [s["download_mbps"] for s in recent_speed]
    speed_up = [s["upload_mbps"] for s in recent_speed]

    outage_rows = ""
    for o in outages[:150]:
        start = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(o["start_ts"]))
        end = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(o["end_ts"])) if o["end_ts"] else "進行中"
        dur = f'{o["duration_sec"] // 60}分{o["duration_sec"] % 60}秒' if o["duration_sec"] else "-"
        reason = o["reason"] or o["type"] or "-"
        outage_rows += f"<tr><td>{start}</td><td>{end}</td><td>{dur}</td><td>{reason}</td></tr>\n"

    log_rows = ""
    for c in list(reversed(checks))[:30]:
        t = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(c["ts"]))
        gw = f'{c["gateway_latency"]:.0f}ms' if c["gateway_latency"] is not None else "-"
        ext = f'{c["external_latency"]:.0f}ms' if c["external_latency"] is not None else "-"
        s_label = status_map.get(c["status"], status_map["unknown"])[1]
        reason = c["reason"] or ""
        log_rows += f"<tr><td>{t}</td><td>{s_label}</td><td>{gw}</td><td>{ext}</td><td style=\"color:#f87171\">{reason}</td></tr>\n"

    nav_html = ""
    if app_mode:
        pause_label = "▶ 繼續監控" if paused else "⏸ 暫停監控"
        nav_html = (
            '<div class="nav">'
            '<a href="/settings">⚙️ 設定</a>'
            '<a href="/api/download-report" download>📄 下載報表</a>'
            '<button onclick="fetch(\'/api/toggle-pause\',{method:\'POST\'}).then(()=>location.reload())">'
            + pause_label + '</button>'
            '</div>'
        )

    refresh_meta = '<meta http-equiv="refresh" content="30">' if app_mode else ''
    report_title = "家用網路監控" if app_mode else f"家用網路監控報表 ({time.strftime('%Y-%m-%d %H:%M:%S')})"

    countdown_script = ""
    if app_mode and next_check_ts:
        countdown_script = f"""
<script>
(function() {{
  var nextCheckTs = {next_check_ts};
  var span = document.getElementById('countdown');
  if (!span) return;
  function tick() {{
    var remaining = Math.round(nextCheckTs - Date.now() / 1000);
    if (remaining <= 0) {{ span.textContent = '即將檢查...'; return; }}
    var m = Math.floor(remaining / 60), s = remaining % 60;
    span.textContent = (m > 0 ? (m + '分') : '') + s + '秒';
  }}
  tick();
  setInterval(tick, 1000);
}})();
</script>
"""

    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{refresh_meta}
<title>{report_title}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
body {{ font-family: -apple-system, "PingFang TC", "Microsoft JhengHei", sans-serif; background:#0f1117; color:#e6e6e6; margin:0; padding:24px; }}
.card {{ background:#1a1d27; border-radius:12px; padding:20px; margin-bottom:20px; }}
.stats {{ display:flex; gap:16px; flex-wrap:wrap; }}
.stat {{ flex:1; min-width:140px; text-align:center; }}
.stat .value {{ font-size:28px; font-weight:bold; }}
.stat .label {{ color:#999; font-size:13px; }}
table {{ width:100%; border-collapse:collapse; }}
th, td {{ text-align:left; padding:8px; border-bottom:1px solid #2a2d3a; font-size:14px; }}
h1 {{ font-size:20px; margin:0; }} h2 {{ font-size:16px; color:#aaa; margin-top:0; }}
.topbar {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; flex-wrap:wrap; gap:10px; }}
.nav a, .nav button {{ color:#ccc; background:#242836; border:none; border-radius:8px; padding:8px 14px; text-decoration:none; font-size:14px; margin-left:8px; cursor:pointer; display:inline-block; }}
.status-banner {{ display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; }}
.badges {{ display:flex; gap:8px; flex-wrap:wrap; align-items:center; }}
.status-badge {{ font-size:22px; font-weight:bold; color:{status_color}; }}
.monitor-badge {{ font-size:13px; font-weight:bold; padding:3px 10px; border-radius:20px; background:#242836; color:{monitor_color}; }}
.detail-line {{ color:#aaa; font-size:13px; margin-top:6px; }}
.reason-line {{ color:#f87171; font-weight:500; }}
.log-wrap {{ max-height:400px; overflow-y:auto; }}
</style>
</head>
<body>
<div class="topbar">
  <h1>{report_title}</h1>
  {nav_html}
</div>

<div class="card">
  <div class="status-banner">
    <div>
      <div class="badges">
        <span class="status-badge">{status_label}</span>
        <span class="monitor-badge">{monitor_label}</span>
      </div>
      <div class="detail-line">最新檢查時間: {latest_time_str}</div>
      <div class="detail-line">{data_line}</div>
      {reason_line}
      <div class="detail-line" id="schedule-line">{schedule_line}</div>
    </div>
    {stats_html}
  </div>
</div>

<div class="card">
  <h2>延遲趨勢 (ms) — 綠:路由器 / 藍:對外</h2>
  <canvas id="latencyChart" height="80"></canvas>
</div>

<div class="card">
  <h2>測速趨勢 (Mbps) — 黃:下載 / 粉:上傳</h2>
  <canvas id="speedChart" height="80"></canvas>
</div>

<div class="card">
  <h2>斷線紀錄(可作為 ISP 申訴佐證)</h2>
  <table>
    <tr><th>開始</th><th>結束</th><th>持續時間</th><th>異常原因</th></tr>
    {outage_rows if outage_rows else '<tr><td colspan="4">目前沒有斷線紀錄 🎉</td></tr>'}
  </table>
</div>

<div class="card">
  <h2>最近檢查紀錄(最新30筆)</h2>
  <div class="log-wrap">
  <table>
    <tr><th>時間</th><th>狀態</th><th>路由器延遲</th><th>對外延遲</th><th>異常原因</th></tr>
    {log_rows if log_rows else '<tr><td colspan="5">尚無資料</td></tr>'}
  </table>
  </div>
</div>

<script>
new Chart(document.getElementById('latencyChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(latency_labels)},
    datasets: [
      {{ label: '路由器延遲', data: {json.dumps(latency_gw)}, borderColor: '#4ade80', tension:0.2, pointRadius:3, pointHoverRadius:5 }},
      {{ label: '對外延遲', data: {json.dumps(latency_ext)}, borderColor: '#60a5fa', tension:0.2, pointRadius:3, pointHoverRadius:5 }}
    ]
  }},
  options: {{ scales: {{ x: {{ ticks: {{ color:'#888', maxTicksLimit:10 }} }}, y: {{ ticks: {{ color:'#888', callback: function(v) {{ return v + ' ms'; }} }} }} }}, plugins:{{legend:{{labels:{{color:'#ccc'}}}}}} }}
}});

new Chart(document.getElementById('speedChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(speed_labels)},
    datasets: [
      {{ label: '下載', data: {json.dumps(speed_down)}, borderColor: '#facc15', tension:0.2, pointRadius:3, pointHoverRadius:5 }},
      {{ label: '上傳', data: {json.dumps(speed_up)}, borderColor: '#f472b6', tension:0.2, pointRadius:3, pointHoverRadius:5 }}
    ]
  }},
  options: {{ scales: {{ x: {{ ticks: {{ color:'#888', maxTicksLimit:10 }} }}, y: {{ ticks: {{ color:'#888', callback: function(v) {{ return v + ' Mbps'; }} }} }} }}, plugins:{{legend:{{labels:{{color:'#ccc'}}}}}} }}
}});
</script>
{countdown_script}
</body>
</html>
"""
    return html


def generate_report(cfg):
    """CLI helper: render and write to cfg['report_path']. Returns the path."""
    out_path = cfg.get("report_path", "report.html")
    html = render_html(cfg, app_mode=False)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path
