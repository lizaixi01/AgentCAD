# AgentCAD desktop icon (Windows). install.create_shortcut fills in the commands below and points the icon at this
# file through "conhost --headless", so no console window ever shows. A small window says what is happening while
# AgentCAD starts; it closes once the browser page is open. AgentCAD keeps running in the background.
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
$zh = (Get-Culture).Name -like 'zh*'
function L($z, $e) { if ($zh) { $z } else { $e } }
$fast = __FAST__   # starts from what is already downloaded (no network), or $null
$full = __FULL__   # may download first
# logs of earlier starts: a running AgentCAD still holds its own (that delete fails quietly), the rest go
Remove-Item -Path (Join-Path $PSScriptRoot 'open-*.log') -ErrorAction SilentlyContinue
$log = Join-Path $PSScriptRoot ('open-' + [guid]::NewGuid().ToString('N') + '.log')

$font = 'Microsoft YaHei UI'
$form = New-Object Windows.Forms.Form
$form.Text = 'AgentCAD'; $form.ClientSize = New-Object Drawing.Size(460, 170)
$form.StartPosition = 'CenterScreen'; $form.FormBorderStyle = 'FixedDialog'; $form.MaximizeBox = $false
$form.BackColor = [Drawing.Color]::White
$ico = Join-Path $PSScriptRoot 'agentcad.ico'
if (Test-Path $ico) { $form.Icon = New-Object Drawing.Icon($ico) }
$title = New-Object Windows.Forms.Label
$title.Font = New-Object Drawing.Font($font, 15, [Drawing.FontStyle]::Bold)
$title.Location = New-Object Drawing.Point(28, 22); $title.Size = New-Object Drawing.Size(410, 36)
$title.Text = (L '__ZH__' '__EN__')
$sub = New-Object Windows.Forms.Label
$sub.Font = New-Object Drawing.Font($font, 11); $sub.ForeColor = [Drawing.Color]::FromArgb(91, 100, 116)
$sub.Location = New-Object Drawing.Point(30, 62); $sub.Size = New-Object Drawing.Size(410, 48)
$sub.Text = (L '马上就好，页面会在浏览器里打开。' 'Almost there. The page opens in your browser.')
$bar = New-Object Windows.Forms.ProgressBar
$bar.Location = New-Object Drawing.Point(30, 116); $bar.Size = New-Object Drawing.Size(400, 22)
$bar.Style = 'Marquee'; $bar.MarqueeAnimationSpeed = 30
$form.Controls.AddRange(@($title, $sub, $bar))

function Run($line) {
  $si = New-Object Diagnostics.ProcessStartInfo
  $si.FileName = 'cmd.exe'; $si.Arguments = '/d /s /c "' + $line + ' > "' + $log + '" 2>&1"'
  $si.UseShellExecute = $false; $si.CreateNoWindow = $true
  [Diagnostics.Process]::Start($si)
}
$script:proc = if ($fast) { Run $fast } else { Run $full }
$script:usedFull = -not $fast

$timer = New-Object Windows.Forms.Timer
$timer.Interval = 250
$timer.Add_Tick({
  $exited = $script:proc.HasExited  # before reading: a quick start can print its link and exit in between
  $text = if (Test-Path $log) { Get-Content -LiteralPath $log -Raw -ErrorAction SilentlyContinue } else { '' }
  if ($text -match '"viewer":\s*"') { $timer.Stop(); $form.Close(); return }
  if ($exited) {
    if (-not $script:usedFull) {  # nothing downloaded yet, or the cache was cleaned: get it
      $script:usedFull = $true
      $sub.Text = (L '第一次打开，正在下载 AgentCAD（大约 1 分钟）…' 'First time: downloading AgentCAD (about a minute)...')
      $script:proc = Run $full
    } else {
      $timer.Stop(); $bar.Style = 'Continuous'; $bar.Value = 0
      $title.Text = (L '没能打开 AgentCAD' 'AgentCAD did not open'); $title.ForeColor = [Drawing.Color]::FromArgb(198, 40, 40)
      $sub.Text = (L '请检查网络连接，然后再双击一次图标。还不行的话，重新运行一次安装程序。' 'Check your internet connection and double-click the icon again. If that does not help, run the installer again.')
    }
  }
})
$form.Add_Shown({ $form.TopMost = $true; $form.Activate(); $form.TopMost = $false; $timer.Start() })
[void]$form.ShowDialog()
