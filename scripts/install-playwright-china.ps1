# 使用 npmmirror 提供的 Playwright / Chrome-for-testing 镜像，减轻国内直连官方 CDN 超时。
# 若提示 404：镜像尚未同步当前 Playwright 版本，可先注释掉 PLAYWRIGHT_DOWNLOAD_HOST 再执行，或过几天重试。
$ErrorActionPreference = "Stop"
if (-not $env:PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT) {
    $env:PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT = "600000"
}
$env:PLAYWRIGHT_DOWNLOAD_HOST = "https://npmmirror.com/mirrors/playwright/chrome-for-testing-public"
if ($args.Count -eq 0) {
    & playwright install chromium
} else {
    & playwright install @args
}
