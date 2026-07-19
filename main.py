#!/usr/bin/env python3
"""NetMon CLI — for people who prefer cron-triggered discrete runs instead
of the persistent app.py server. Most people should just run app.py.

用法 (由 cron 排程呼叫):
    python main.py --mode check
    python main.py --mode speedtest
    python main.py --mode report
"""

import json
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine import run_check, run_speedtest, with_defaults


def load_config(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"))
    parser.add_argument("--mode", choices=["check", "speedtest", "report"], required=True)
    args = parser.parse_args()

    cfg = with_defaults(load_config(args.config))

    if args.mode == "check":
        print(run_check(cfg))
    elif args.mode == "speedtest":
        d, u, p = run_speedtest(cfg)
        print(f"down={d} up={u} ping={p}")
    elif args.mode == "report":
        from report import generate_report
        path = generate_report(cfg)
        print(f"report written to {path}")
