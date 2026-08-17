# OpenRouter 模型调用量追踪器

抓取 OpenRouter 公开 rankings 接口，统计**各家模型的每日调用次数与 Token 用量**，
结构对齐 `gpu-price-tracker`：独立抓取脚本 + 自包含静态仪表盘 HTML。

## 数据源
- 接口：`https://openrouter.ai/api/frontend/v1/rankings/models`（公开、免鉴权）
- 字段：`count`（调用次数）、`total_prompt_tokens`、`total_completion_tokens`、
  `total_native_tokens_reasoning`、`variant`（standard/batch/free）、`change`（环比）等
- 同一模型的多 variant 已按 `model_permaslug` 聚合；厂商从 slug 前缀推断
  （openai / google / deepseek / qwen / tencent / x-ai …）

## 文件
- `scrape_openrouter.py` — 抓取脚本（纯标准库，零依赖）。每次运行抓近几天数据，
  按 `YYYY-MM-DD` 归档到 `model_stats.json`，并把最新数据嵌进 `model_stats.html`
- `model_stats.html` — 自包含仪表盘（内嵌数据 + 纯 JS/SVG 图表，离线可看）
- `model_stats.json` — 历史数据（按日期归档，最多保留 365 天）
- `run_scraper.bat` — Windows 直接双击/计划任务调用
- `scheduler/setup_schedule.ps1` — 注册每日 09:00 计划任务

## 手动运行
```
cd C:\Users\fengz\openrouter-model-tracker
C:\Users\fengz\AppData\Local\Programs\Python\Python314\python.exe scrape_openrouter.py
```
或直接双击 `run_scraper.bat`（日志写入 `scrape.log`）。

## 设为每日自动抓取（对齐 gpu pricer）
在本机以普通权限运行（当前 WorkBuddy 沙箱禁用了 schtasks，需在本机执行）：
```
powershell -ExecutionPolicy Bypass -File C:\Users\fengz\openrouter-model-tracker\scheduler\setup_schedule.ps1
```
即可注册 `OpenRouterModelStats` 任务，每日 09:00 运行（与 GPUPriceTracker / MemoryPriceScraper 同档）。

## 仪表盘说明
- 顶部汇总卡片：当日模型数、总调用次数、总 Prompt Tokens、活跃厂商/头部模型
- 调用量 Top 排行：横向条形图（按当前筛选，颜色区分厂商）
- 每日总调用量趋势：折线图（跨历史日期）
- 明细表：可搜索、按厂商筛选、点表头排序、Top N 切换

> 注：`change`（环比）字段在接口无时间窗参数时多为 null，显示为「—」；
> 若以后需要周环比，可在抓取时追加接口的时间窗参数。
