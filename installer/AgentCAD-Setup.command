#!/bin/sh
# AgentCAD installer for macOS and Linux: double-click it (macOS) or run it. It gets uv (a small tool that runs
# Python programs) if this computer has none, then opens the setup page in your browser (agentcad setup --gui).
echo
echo "   AgentCAD 安装 / Setup"
echo "   ------------------------------------------------------------"
echo "   正在准备，请稍候。安装页面会自动在浏览器里打开。"
echo "   Getting ready. The setup page will open in your browser."
echo "   请不要关闭这个窗口。Please keep this window open."
echo
export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "   第一次使用：正在下载需要的小工具，大约 1 分钟……"
  echo "   First time: downloading a small helper tool, about a minute..."
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
fi
if command -v uvx >/dev/null 2>&1 && uvx --refresh-package agentcad-runtime --from https://github.com/lizaixi01/AgentCAD/archive/refs/heads/main.zip agentcad setup --gui >/dev/null; then
  exit 0
fi
echo
echo "   没能完成安装。请检查网络连接，然后再打开一次这个文件。"
echo "   Setup could not finish. Check your internet connection and open this file again."
printf "   按回车键关闭 / Press Enter to close "
read _
exit 1
