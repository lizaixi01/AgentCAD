@echo off
rem AgentCAD installer for Windows: double-click it. A small window with a progress bar gets uv (a tool that runs
rem Python programs) if this computer has none and downloads AgentCAD, then the setup page opens in your browser
rem (agentcad setup --gui). Nothing to type. The PowerShell part below the marker draws that window.
set "AGENTCAD_SETUP_FILE=%~f0"
if not "%AGENTCAD_SOURCE%"=="" goto start
set "AGENTCAD_SOURCE=https://github.com/lizaixi01/AgentCAD/archive/refs/heads/main.zip"
:start
rem wscript runs PowerShell with window style 0: no console, also where Windows Terminal is the default console
rem (it ignores -WindowStyle Hidden). JScript, not VBScript, which Windows is phasing out. Where Windows Script Host
rem is switched off (some company PCs): conhost --headless (Windows 10 1809 and later).
reg query "HKCU\Software\Microsoft\Windows Script Host\Settings" /v Enabled 2>nul | findstr /r /e /c:"0x0" /c:"REG_SZ *0" >nul && goto noscripthost
reg query "HKLM\Software\Microsoft\Windows Script Host\Settings" /v Enabled 2>nul | findstr /r /e /c:"0x0" /c:"REG_SZ *0" >nul && goto noscripthost
set "AGENTCAD_SETUP_JS=%TEMP%\agentcad-setup.js"
> "%AGENTCAD_SETUP_JS%" echo new ActiveXObject("WScript.Shell").Run("powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command \"$t = Get-Content -LiteralPath $env:AGENTCAD_SETUP_FILE -Raw -Encoding UTF8; iex ($t -split ('#PS' + '-START#'), 2)[1]\"", 0, false);
start "" wscript.exe //E:JScript "%AGENTCAD_SETUP_JS%"
exit /b 0
:noscripthost
start "" conhost.exe --headless powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "$t = Get-Content -LiteralPath $env:AGENTCAD_SETUP_FILE -Raw -Encoding UTF8; iex ($t -split ('#PS' + '-START#'), 2)[1]"
exit /b 0
#PS-START#
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$zh = (Get-Culture).Name -like 'zh*'
function L($z, $e) { if ($zh) { $z } else { $e } }
$src = $env:AGENTCAD_SOURCE
$extra = @(); if ($env:AGENTCAD_SETUP_ARGS) { $extra = $env:AGENTCAD_SETUP_ARGS -split ' ' }

$font = 'Microsoft YaHei UI'
$form = New-Object Windows.Forms.Form
$form.Text = (L 'AgentCAD 安装' 'AgentCAD Setup')
$form.ClientSize = New-Object Drawing.Size(560, 270)
$form.StartPosition = 'CenterScreen'; $form.FormBorderStyle = 'FixedDialog'; $form.MaximizeBox = $false
$form.BackColor = [Drawing.Color]::White
$title = New-Object Windows.Forms.Label
$title.Font = New-Object Drawing.Font($font, 18, [Drawing.FontStyle]::Bold)
$title.Location = New-Object Drawing.Point(32, 26); $title.Size = New-Object Drawing.Size(500, 44)
$title.Text = (L '正在准备 AgentCAD…' 'Getting AgentCAD ready…')
$step = New-Object Windows.Forms.Label
$step.Font = New-Object Drawing.Font($font, 12)
$step.ForeColor = [Drawing.Color]::FromArgb(91, 100, 116)
$step.Location = New-Object Drawing.Point(34, 78); $step.Size = New-Object Drawing.Size(500, 56)
$bar = New-Object Windows.Forms.ProgressBar
$bar.Location = New-Object Drawing.Point(34, 142); $bar.Size = New-Object Drawing.Size(492, 26)
$bar.Minimum = 0; $bar.Maximum = 1000
$pct = New-Object Windows.Forms.Label
$pct.Font = New-Object Drawing.Font($font, 11)
$pct.Location = New-Object Drawing.Point(34, 176); $pct.Size = New-Object Drawing.Size(300, 28)
$btn = New-Object Windows.Forms.Button
$btn.Font = New-Object Drawing.Font($font, 12, [Drawing.FontStyle]::Bold)
$btn.Location = New-Object Drawing.Point(326, 206); $btn.Size = New-Object Drawing.Size(200, 46)
$btn.Visible = $false
$form.Controls.AddRange(@($title, $step, $bar, $pct, $btn))

$script:goal = 0; $script:ceil = 0; $script:url = $null; $script:proc = $null; $script:phase = 'uv'
function SetStep($text, $from, $to) { $step.Text = $text; $script:goal = $from; $script:ceil = $to }
function Fail($text) {
  $script:phase = 'failed'; $title.Text = (L '没能完成安装' 'Setup could not finish')
  $title.ForeColor = [Drawing.Color]::FromArgb(198, 40, 40); $step.Text = $text
  $btn.Text = (L '关闭' 'Close'); $btn.Visible = $true; $btn.Add_Click({ $form.Close() })
}

$uvDir = Join-Path $env:USERPROFILE '.local\bin'
$env:PATH = "$uvDir;$env:PATH"
$out = Join-Path $env:TEMP ("agentcad-setup-" + [guid]::NewGuid().ToString('N') + '.log')
function Run($line) {
  # cmd.exe does the redirection; CreateNoWindow keeps every console out of sight
  $si = New-Object Diagnostics.ProcessStartInfo
  $si.FileName = 'cmd.exe'; $si.Arguments = '/d /s /c "' + $line + '"'
  $si.UseShellExecute = $false; $si.CreateNoWindow = $true
  [Diagnostics.Process]::Start($si)
}

function StartAgentCAD {
  $script:phase = 'agentcad'
  SetStep (L '第 2 步，共 2 步：下载 AgentCAD（第一次大约 1 分钟）' 'Step 2 of 2: downloading AgentCAD (about a minute the first time)') 400 950
  $script:proc = Run ('uvx --refresh-package agentcad-runtime --from "' + $src + '" agentcad setup --gui ' + ($extra -join ' ') + ' > "' + $out + '" 2> "' + $out + '.err"')
}

if (Get-Command uvx -ErrorAction SilentlyContinue) {
  StartAgentCAD
} else {
  SetStep (L '第 1 步，共 2 步：下载需要的小工具（大约 1 分钟）' 'Step 1 of 2: downloading a small helper tool (about a minute)') 0 380
  $script:proc = Run 'powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"' 
}

$timer = New-Object Windows.Forms.Timer
$timer.Interval = 200
$timer.Add_Tick({
  # creep toward the end of the current step, so the bar always moves
  if ($script:goal -lt $script:ceil) { $script:goal += [Math]::Max(1, [int](($script:ceil - $script:goal) / 60)) }
  if ($bar.Value -lt $script:goal) { $bar.Value = [Math]::Min($bar.Maximum, $script:goal) }
  $pct.Text = "{0}%" -f [int]($bar.Value / 10)
  if ($script:phase -eq 'uv' -and $script:proc.HasExited) {
    if (Get-Command uvx -ErrorAction SilentlyContinue) { StartAgentCAD }
    else { Fail (L '没能下载需要的小工具。请检查网络连接，然后再双击一次安装程序。' 'Could not download the helper tool. Check your internet connection and double-click the installer again.') }
  } elseif ($script:phase -eq 'agentcad') {
    $text = if (Test-Path $out) { Get-Content -LiteralPath $out -Raw -ErrorAction SilentlyContinue } else { '' }
    if ($text -match '"setup":\s*"([^"]+)"') {
      $script:url = $Matches[1]; $script:phase = 'open'
      $script:goal = 1000; $script:ceil = 1000; $bar.Value = 1000; $pct.Text = '100%'
      $title.Text = (L '请在浏览器里继续' 'Continue in your browser')
      $step.Text = (L '安装页面已经在浏览器里打开了。装好后这个窗口会自己关掉。' 'The setup page is open in your browser. This window closes by itself when you finish.')
      $btn.Text = (L '重新打开安装页面' 'Open the page again'); $btn.Visible = $true
      $btn.Add_Click({ Start-Process $script:url })
    } elseif ($script:proc.HasExited) {
      Fail (L '没能下载 AgentCAD。请检查网络连接，然后再双击一次安装程序。' 'Could not download AgentCAD. Check your internet connection and double-click the installer again.')
    }
  } elseif ($script:phase -eq 'open' -and $script:proc.HasExited) {
    $form.Close()
  }
})
$form.Add_Shown({
  # started from a hidden console, the window would open behind the others: lift it once
  $form.TopMost = $true; $form.Activate(); $form.TopMost = $false
  $timer.Start()
})
$form.Add_FormClosing({
  param($sender, $e)
  if ($script:phase -eq 'open' -and -not $script:proc.HasExited) {
    $e.Cancel = $true; $form.WindowState = 'Minimized'  # the setup page still needs it; it closes when you finish
  } elseif ($script:proc -and -not $script:proc.HasExited) {
    & taskkill.exe /T /F /PID $script:proc.Id | Out-Null  # closed while downloading: stop everything it started
  }
})
$form.Add_FormClosed({ $timer.Stop() })
[void]$form.ShowDialog()
