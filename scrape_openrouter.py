#!/usr/bin/env python3
"""
OpenRouter 模型调用量追踪器 — 每日时间序列采集器 (daily collector)

抓取 OpenRouter 公开 rankings 接口，统计各家模型的「调用次数 / Token 用量」，
结构完全对齐 gpu-price-tracker：
  - 抓 -> 写 model_stats.json (按 YYYY-MM-DD 归档的历史)
  - 把最新数据 embed 进 model_stats.html (自包含仪表盘)

数据源（公开、免鉴权）：
  https://openrouter.ai/api/frontend/v1/rankings/models
  每条记录含：date, model_permaslug, variant, count(调用次数),
  total_prompt_tokens, total_completion_tokens, change(环比) 等。

设计为可每天重复运行：每次刷新接口返回的近几天数据，按日期归档，
同日期会覆盖，不会重复累积。

仅依赖 Python 标准库（urllib），无需 venv / requests。
"""

import io
import json
import re
import sys
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# ── Windows UTF-8 ──
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = SCRIPT_DIR / "model_stats.json"
HTML_FILE = SCRIPT_DIR / "model_stats.html"
LOG_FILE = SCRIPT_DIR / "scrape.log"

RANKINGS_URL = "https://openrouter.ai/api/frontend/v1/rankings/models"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; openrouter-model-tracker/1.0)",
    "Accept": "application/json",
}

NOW = datetime.now(timezone.utc)
ISO_TIME = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
HISTORY_CAP = 365

# 厂商前缀 -> 展示中文/短名（仅用于表格友好显示，不影响统计）
PROVIDER_ALIAS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "deepseek": "DeepSeek",
    "qwen": "Qwen",
    "mistralai": "Mistral",
    "meta-llama": "Meta",
    "x-ai": "xAI",
    "tencent": "Tencent",
    "nvidia": "NVIDIA",
    "z-ai": "Z.ai",
    "minimax": "MiniMax",
    "moonshot": "Moonshot",
    "alibaba": "Alibaba",
    "microsoft": "Microsoft",
}


def log(msg: str) -> None:
    line = f"[{ISO_TIME}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except IOError:
        pass


def fetch_rankings():
    """抓取 OpenRouter rankings/models，返回原始记录列表。"""
    req = Request(RANKINGS_URL, headers=HEADERS)
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise ValueError(f"unexpected payload shape: {type(data)}")
    return data


def clean_model_name(permaslug: str) -> str:
    """从 permaslug 取干净模型名：去掉厂商前缀与尾部 -YYYYMMDD 版本号。"""
    name = permaslug.split("/", 1)[-1]
    name = re.sub(r"-20\d{6}$", "", name)          # 去掉 -20260423 之类
    name = re.sub(r"-\d{8}$", "", name)             # 兜底
    return name


def aggregate(raw_rows):
    """
    按 date -> model_permaslug 聚合（同一模型的多 variant 求和）。
    返回 { "YYYY-MM-DD": [model_record, ...] }
    """
    by_date = defaultdict(lambda: defaultdict(lambda: {
        "count": 0, "prompt_tokens": 0, "completion_tokens": 0,
        "reasoning_tokens": 0, "native_tokens_cached": 0, "tool_calls": 0,
        "variants": set(), "change": None,
    }))

    for r in raw_rows:
        date_key = (r.get("date") or "")[:10]
        if not date_key:
            continue
        slug = r.get("model_permaslug") or r.get("variant_permaslug")
        if not slug:
            continue
        bucket = by_date[date_key][slug]
        bucket["count"] += int(r.get("count") or 0)
        bucket["prompt_tokens"] += int(r.get("total_prompt_tokens") or 0)
        bucket["completion_tokens"] += int(r.get("total_completion_tokens") or 0)
        bucket["reasoning_tokens"] += int(r.get("total_native_tokens_reasoning") or 0)
        bucket["native_tokens_cached"] += int(r.get("total_native_tokens_cached") or 0)
        bucket["tool_calls"] += int(r.get("total_tool_calls") or 0)
        if r.get("variant"):
            bucket["variants"].add(r["variant"])
        # change 取非 None 的（通常 standard 行带环比）
        if bucket["change"] is None and r.get("change") is not None:
            bucket["change"] = r.get("change")

    out = {}
    for date_key, models in by_date.items():
        recs = []
        for slug, b in models.items():
            provider = slug.split("/", 1)[0]
            recs.append({
                "model_permaslug": slug,
                "model_name": clean_model_name(slug),
                "provider": provider,
                "provider_alias": PROVIDER_ALIAS.get(provider, provider),
                "count": b["count"],
                "prompt_tokens": b["prompt_tokens"],
                "completion_tokens": b["completion_tokens"],
                "reasoning_tokens": b["reasoning_tokens"],
                "total_tokens": b["prompt_tokens"] + b["completion_tokens"],
                "native_tokens_cached": b["native_tokens_cached"],
                "tool_calls": b["tool_calls"],
                "variants": sorted(b["variants"]),
                "change": b["change"],
                "scrape_time": ISO_TIME,
            })
        out[date_key] = recs
    return out


def load_existing():
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            log("WARN: existing JSON unreadable, starting fresh")
    return {"last_updated": None, "history": {}}


def save(data):
    data["last_updated"] = ISO_TIME
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log(f"Saved {OUTPUT_FILE.name}")
    embed_in_html(data)


def embed_in_html(data):
    """把 EMBEDDED_DATA 字面量就地替换进 model_stats.html。"""
    if not HTML_FILE.exists():
        log(f"WARN: {HTML_FILE.name} missing; skipping embed")
        return
    html = HTML_FILE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False)
    pattern = re.compile(r"const\s+EMBEDDED_DATA\s*=\s*\{.*?\};", re.DOTALL)
    if not pattern.search(html):
        log(f"WARN: EMBEDDED_DATA marker not found in {HTML_FILE.name}")
        return
    new_html = pattern.sub(f"const EMBEDDED_DATA = {payload};", html, count=1)
    if new_html != html:
        HTML_FILE.write_text(new_html, encoding="utf-8")
        log(f"Updated {HTML_FILE.name}")


def main():
    log("=== OpenRouter Model Stats run ===")
    try:
        raw = fetch_rankings()
    except Exception:
        log("FATAL during fetch():\n" + traceback.format_exc())
        sys.exit(1)

    log(f"Fetched {len(raw)} raw rows")

    aggregated = aggregate(raw)
    dates = sorted(aggregated.keys())
    log(f"Aggregated into {len(dates)} dates: {dates[0]} .. {dates[-1]}")

    data = load_existing()
    for d in dates:
        data["history"][d] = aggregated[d]

    # 截断到最近 HISTORY_CAP 天
    all_dates = sorted(data["history"].keys())
    while len(all_dates) > HISTORY_CAP:
        removed = all_dates.pop(0)
        del data["history"][removed]

    save(data)

    # 当天摘要
    latest = sorted(data["history"].keys())[-1]
    rows = data["history"][latest]
    total_calls = sum(r["count"] for r in rows)
    total_pt = sum(r["prompt_tokens"] for r in rows)
    providers = sorted({r["provider"] for r in rows})
    print("\n=== Latest snapshot ({}): {} models ===".format(latest, len(rows)))
    print(f"  total calls : {total_calls:,}")
    print(f"  total prompt tokens : {total_pt:,}")
    print(f"  providers : {len(providers)}")
    top = sorted(rows, key=lambda r: r["count"], reverse=True)[:5]
    for r in top:
        print(f"  {r['model_permaslug']:42} calls={r['count']:>12,} pt={r['prompt_tokens']:>15,}")


if __name__ == "__main__":
    main()
