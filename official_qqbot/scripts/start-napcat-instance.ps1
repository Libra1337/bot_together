param(
  [Parameter(Mandatory = $true)]
  [ValidateSet("qqbot", "only-group-bot")]
  [string]$Instance
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$Launcher = Join-Path $ScriptDir "napcat-launcher.cjs"

if (-not (Test-Path $Launcher)) {
  throw "NapCat launcher not found: $Launcher"
}

Set-Location $ProjectRoot
node.exe $Launcher "--instance=$Instance"
exit $LASTEXITCODE
