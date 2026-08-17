# setup_schedule.ps1
# 注册 Windows 计划任务：每日 09:00 抓取 OpenRouter 模型调用量（对齐 gpu-price-tracker）。
# 在本机以普通权限运行（无需管理员）：  powershell -ExecutionPolicy Bypass -File setup_schedule.ps1
# 说明：使用 Interactive 登录类型 = 仅当用户登录时运行，不存储密码，不会弹窗要密码。
$ErrorActionPreference = "Stop"

$TaskName  = "OpenRouterModelStats"
$ProjectDir = "C:\Users\fengz\openrouter-model-tracker"
$Bat        = Join-Path $ProjectDir "run_scraper.bat"

# 1) 动作：用 cmd 跑 bat（bat 内部已写好 python 路径与日志）
$action = New-ScheduledTaskAction `
    -Execute "C:\Windows\System32\cmd.exe" `
    -Argument "/c `"$Bat`""

# 2) 触发器：每天 09:00
$trigger = New-ScheduledTaskTrigger -Daily -At "09:00"

# 3) 主体：当前用户，仅登录时运行，最高权限
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Highest

# 4) 注册（如已存在则覆盖）
Register-ScheduledTask -TaskName $TaskName `
    -Action $action -Trigger $trigger -Principal $principal `
    -Description "OpenRouter 模型调用量每日追踪（对齐 gpu-price-tracker）" -Force

Write-Host "已创建/更新计划任务: $TaskName （每日 09:00）"
Write-Host "可到 任务计划程序 -> 任务计划程序库 中查看，或运行：  schtasks /query /tn $TaskName"
