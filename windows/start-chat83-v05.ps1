# CHAT83 v0.5 Windows launcher. Start Python first, then TI C83V5.
param(
  [string]$Port = "COM2",
  [ValidateSet("demo","gemini","openai","ollama")]
  [string]$Provider = "demo",
  [string]$Model = "",
  [int]$GapMs = 35,
  [int]$ReplyDelayMs = 250,  # real hardware-verified turnaround
  [switch]$DebugLink,
  [switch]$WordWrap,
  [string]$Db = "",
  [switch]$Adaptive,
  [switch]$Verbose,
  [string]$OllamaUrl = "http://127.0.0.1:11434"
)
$ErrorActionPreference = "Stop"
if ($GapMs -lt 2 -or $GapMs -gt 50) {
  throw "GapMs must be between 2 and 50"
}
if ($ReplyDelayMs -lt 0 -or $ReplyDelayMs -gt 1500) {
  throw "ReplyDelayMs must be between 0 and 1500"
}
if (-not $Db) {
  $Db = Join-Path $PSScriptRoot "chat83_v05.sqlite3"
}
$script = Join-Path $PSScriptRoot "bridge_v05.py"
if (-not (Test-Path $script)) {
  throw "bridge_v05.py not found in $PSScriptRoot. Extract the full test kit into one folder."
}
$argsList = @($script, "--port", $Port, "--provider", $Provider,
              "--gap-ms", [string]$GapMs, "--db", $Db,
              "--ollama-url", $OllamaUrl,
              "--reply-delay-ms", [string]$ReplyDelayMs)
if ($Model) { $argsList += @("--model", $Model) }
if ($Adaptive) { $argsList += "--adaptive" }
if ($Verbose) { $argsList += "--verbose" }
if ($DebugLink) { $argsList += "--debug-link" }
if ($WordWrap) { $argsList += "--word-wrap" }
Write-Host "Starting CHAT83 v0.5 on $Port / provider=$Provider / gap=$($GapMs)ms / turnaround=$($ReplyDelayMs)ms"
& py @argsList
exit $LASTEXITCODE
