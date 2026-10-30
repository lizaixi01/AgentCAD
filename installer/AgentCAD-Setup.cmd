@echo off
rem AgentCAD installer for Windows: double-click it. It gets uv (a small tool that runs Python programs) if this
rem computer has none, then opens the setup page in your browser (agentcad setup --gui). Nothing to type.
chcp 65001 >nul
title AgentCAD
echo.
echo    AgentCAD 安装 / Setup
echo    ------------------------------------------------------------
echo    正在准备，请稍候。安装页面会自动在浏览器里打开。
echo    Getting ready. The setup page will open in your browser.
echo.
echo    请不要关闭这个窗口，安装完成后它会自己关掉。
echo    Please keep this window open. It closes by itself when you finish.
echo.
where uv >nul 2>nul && goto run
if exist "%USERPROFILE%\.local\bin\uv.exe" goto addpath
echo    第一次使用：正在下载需要的小工具，大约 1 分钟……
echo    First time: downloading a small helper tool, about a minute...
powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex" >nul
if not exist "%USERPROFILE%\.local\bin\uv.exe" goto failed
:addpath
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
:run
echo    正在打开安装页面……  Opening the setup page...
uvx --refresh-package agentcad-runtime --from https://github.com/lizaixi01/AgentCAD/archive/refs/heads/main.zip agentcad setup --gui >nul
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo    没能完成安装。请检查网络连接，然后再双击一次这个文件。
echo    Setup could not finish. Check your internet connection and double-click this file again.
echo.
pause
exit /b 1
