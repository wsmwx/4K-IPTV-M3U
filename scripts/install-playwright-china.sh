#!/usr/bin/env bash
# 国内镜像安装 Playwright 浏览器（npmmirror → chrome-for-testing-public）
# 若 404：镜像未同步当前版本，可 unset PLAYWRIGHT_DOWNLOAD_HOST 后重试。
set -euo pipefail
export PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT="${PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT:-600000}"
export PLAYWRIGHT_DOWNLOAD_HOST="https://npmmirror.com/mirrors/playwright/chrome-for-testing-public"
if [ "$#" -eq 0 ]; then
  exec playwright install chromium
else
  exec playwright install "$@"
fi
