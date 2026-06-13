# Zaude bootstrap installer (Windows / PowerShell 5.1-safe)
param([switch]$WireClaude)
$ErrorActionPreference = "Stop"
$src = Split-Path -Parent $MyInvocation.MyCommand.Path
$dst = Join-Path $HOME ".zaude"
$py = $null
foreach ($c in @("python","python3")) {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if ($cmd) { $py = $cmd.Source; break }
}
if (-not $py) { Write-Error "Python 3 is required but was not found on PATH."; exit 1 }
Write-Host "Installing Zaude to $dst ..."
foreach ($sub in @("bin","policy","kernel")) {
  $s = Join-Path $src $sub
  if (Test-Path $s) {
    $d = Join-Path $dst $sub
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    Copy-Item -Recurse -Force (Join-Path $s "*") $d
  }
}
& $py (Join-Path $dst "bin\zaude.py") gen
Write-Host ""
Write-Host "Zaude installed (kernel $(Get-Content (Join-Path $dst 'kernel\CURRENT')))."
if ($WireClaude) {
  & $py (Join-Path $dst "bin\zaude.py") install --yes
} else {
  Write-Host "To wire the /z* slash commands + the fail-open hook into ~/.claude, run:"
  Write-Host "  python `"$dst\bin\zaude.py`" install --yes"
}
Write-Host "Note: copy your GitHub PAT to ~/.zaude/secrets/github-pat to enable the PM board."
