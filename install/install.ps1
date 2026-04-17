# Zaude installer — Windows PowerShell (5.1+ or 7+).
# Non-interactive alternative to install/setup-prompt.md.
#
# Usage:
#   irm https://raw.githubusercontent.com/ziadmomen10/zaude/main/install/install.ps1 | iex
#   (or)  .\install.ps1

$ErrorActionPreference = "Stop"

$RepoUrl = "https://github.com/ziadmomen10/zaude.git"

function Say($msg)   { Write-Host "▸ $msg" -ForegroundColor Cyan }
function Ok($msg)    { Write-Host "✓ $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "! $msg" -ForegroundColor Yellow }
function Die($msg)   { Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }

function Require-Command($cmd) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Die "$cmd is required but not found on PATH."
    }
}

function Ask($prompt, $default) {
    $defaultHint = if ($default) { " [$default]" } else { "" }
    $answer = Read-Host "$prompt$defaultHint"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $default }
    return $answer
}

function AskYesNo($prompt, $defaultYes = $false) {
    $hint = if ($defaultYes) { "[Y/n]" } else { "[y/N]" }
    $answer = Read-Host "$prompt $hint"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $defaultYes }
    return $answer -match '^[Yy]'
}

# banner
@"

   ╔══════════════════════════════════════════╗
   ║                                          ║
   ║   ███████╗ █████╗ ██╗   ██╗██████╗ ███████╗
   ║   ╚══███╔╝██╔══██╗██║   ██║██╔══██╗██╔════╝
   ║     ███╔╝ ███████║██║   ██║██║  ██║█████╗
   ║    ███╔╝  ██╔══██║██║   ██║██║  ██║██╔══╝
   ║   ███████╗██║  ██║╚██████╔╝██████╔╝███████╗
   ║   ╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝
   ║                                          ║
   ║      Don't vibe code. Zaude code.        ║
   ╚══════════════════════════════════════════╝

"@ | Write-Host -ForegroundColor Cyan

Say "Checking prerequisites..."
Require-Command git
$pythonCmd = if (Get-Command python3 -ErrorAction SilentlyContinue) { "python3" } `
             elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } `
             else { Die "python3 or python required on PATH." }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Warn "gh CLI not found. GitHub repo creation will be skipped. Install from https://cli.github.com"
}
Ok "Prerequisites OK."

$VaultPath     = Ask "Where should your vault live?" "$HOME\zaude-vault"
$GhUser        = ""
if (Get-Command gh -ErrorAction SilentlyContinue) {
    $GhUser = (gh api user --jq .login 2>$null) -as [string]
    if (-not $GhUser) { Warn "gh is installed but not authenticated. Run: gh auth login" }
}
$GhUser        = Ask "GitHub username for private repos" $GhUser
$ProjectSlug   = Ask "First project slug (lowercase-with-dashes)" "my-first-project"
$ProjectCwd    = Ask "Current working directory for that project (absolute path)" "$HOME\$ProjectSlug"
$ProjectCwdBase = Split-Path $ProjectCwd -Leaf
$FrozenZones   = Ask "Frozen path substrings (comma-separated, or blank for none)" ""

# Clone
$TmpDir = Join-Path $env:TEMP "zaude-install-$(Get-Random)"
New-Item -Path $TmpDir -ItemType Directory -Force | Out-Null
try {
    Say "Cloning Zaude into $TmpDir..."
    git clone --depth 1 $RepoUrl "$TmpDir\zaude" 2>$null | Out-Null
    Ok "Cloned."

    # Vault
    Say "Creating vault at $VaultPath..."
    if (Test-Path $VaultPath) {
        if (-not (AskYesNo "Vault directory exists. Overwrite non-clashing files only (safe)?" $true)) {
            Die "Aborted by user."
        }
    }
    New-Item -Path $VaultPath -ItemType Directory -Force | Out-Null
    Copy-Item "$TmpDir\zaude\templates\vault\*" -Destination $VaultPath -Recurse -Force

    $templateProjDir = Join-Path $VaultPath "01-projects\_template"
    if (Test-Path $templateProjDir) {
        Rename-Item $templateProjDir -NewName $ProjectSlug
    }
    Ok "Vault scaffolded. First project: $ProjectSlug"

    # Claude config
    $ClaudeDir = "$HOME\.claude"
    New-Item -Path "$ClaudeDir\commands" -ItemType Directory -Force | Out-Null
    New-Item -Path "$ClaudeDir\hooks" -ItemType Directory -Force | Out-Null

    Say "Installing hooks..."
    Get-ChildItem "$TmpDir\zaude\templates\claude-config\hooks\*" | ForEach-Object {
        $dest = Join-Path "$ClaudeDir\hooks" $_.Name
        if (Test-Path $dest) {
            if (AskYesNo "  $dest exists. Overwrite?" $false) { Copy-Item $_.FullName $dest -Force }
        } else {
            Copy-Item $_.FullName $dest
        }
    }
    Ok "Hooks installed."

    Say "Installing commands..."
    Get-ChildItem "$TmpDir\zaude\templates\claude-config\commands\*.md" | ForEach-Object {
        $dest = Join-Path "$ClaudeDir\commands" $_.Name
        if (Test-Path $dest) {
            if (AskYesNo "  $dest exists. Overwrite?" $false) { Copy-Item $_.FullName $dest -Force }
        } else {
            Copy-Item $_.FullName $dest
        }
    }
    Ok "Commands installed."

    # settings.json
    $Settings = "$ClaudeDir\settings.json"
    if (-not (Test-Path $Settings)) {
        Copy-Item "$TmpDir\zaude\templates\claude-config\settings.json" $Settings
        Ok "settings.json created."
    } else {
        Warn "$Settings already exists. Zaude won't overwrite it."
        Warn "Compare against templates/claude-config/settings.json and merge the hook entries manually."
    }

    # Global CLAUDE.md
    $GlobalMd = "$ClaudeDir\CLAUDE.md"
    if (-not (Test-Path $GlobalMd)) {
        Copy-Item "$TmpDir\zaude\templates\claude-config\CLAUDE.md" $GlobalMd
        Ok "Global CLAUDE.md created."
    } else {
        Warn "$GlobalMd exists. Appending Zaude section with a separator."
        $today = Get-Date -Format 'yyyy-MM-dd'
        $separator = "`n`n---`n`n<!-- Zaude framework — appended by install.ps1 $today -->`n"
        $zaudeContent = Get-Content "$TmpDir\zaude\templates\claude-config\CLAUDE.md" -Raw
        Add-Content -Path $GlobalMd -Value ($separator + $zaudeContent)
    }

    # Zaude config
    $ZaudeDir = "$HOME\.zaude"
    New-Item -Path $ZaudeDir -ItemType Directory -Force | Out-Null
    $Config = "$ZaudeDir\config.json"

    $frozenList = @()
    if ($FrozenZones) { $frozenList = $FrozenZones.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ } }
    $cwdMap = @{}
    if ($ProjectCwdBase -and $ProjectSlug) { $cwdMap[$ProjectCwdBase] = $ProjectSlug }

    $cfg = [ordered]@{
        vault_path = $VaultPath
        projects_subdir = "01-projects"
        patterns_subdir = "03-patterns"
        cwd_to_project = $cwdMap
        frozen_zones = $frozenList
        recent_session_logs = 3
        claude_config_path = $ClaudeDir
    }
    $cfg | ConvertTo-Json -Depth 5 | Set-Content $Config -Encoding UTF8
    Ok "Wrote $Config"

    # GitHub repos
    if ((Get-Command gh -ErrorAction SilentlyContinue) -and $GhUser) {
        if (AskYesNo "Create private GitHub repos for vault + claude-config?" $true) {
            Say "Creating github.com/$GhUser/zaude-vault (private)..."
            gh repo create "$GhUser/zaude-vault" --private --description "My Zaude vault" 2>$null | Out-Null

            Say "Creating github.com/$GhUser/zaude-claude-config (private)..."
            gh repo create "$GhUser/zaude-claude-config" --private --description "My Zaude Claude-Code config" 2>$null | Out-Null

            Say "Initializing vault git repo..."
            Push-Location $VaultPath
            try {
                git init -b main -q 2>$null
                git add -A 2>$null
                git commit -m "Initial Zaude vault" -q 2>$null
                git remote add origin "https://github.com/$GhUser/zaude-vault.git" 2>$null
                git push -u origin main -q 2>$null
                Ok "Vault pushed."
            } finally { Pop-Location }

            Say "Initializing ~/.claude git repo with curated .gitignore..."
            Push-Location $ClaudeDir
            try {
                if (-not (Test-Path "$ClaudeDir\.git")) { git init -b main -q 2>$null }
                if (-not (Test-Path "$ClaudeDir\.gitignore")) {
                    @"
*
!commands/
!commands/**
!hooks/
!hooks/**
!agents/
!agents/**
!skills/
!skills/**
!CLAUDE.md
!settings.json
!.gitignore
!README.md
!projects/
!projects/*/
!projects/*/memory/
!projects/*/memory/**
**/*.log
**/*.credentials.json
**/.credentials.json
"@ | Set-Content "$ClaudeDir\.gitignore" -Encoding UTF8
                }
                git add -A 2>$null
                $staged = git diff --cached --quiet 2>$null; $LASTEXITCODE
                if ($LASTEXITCODE -eq 0) {
                    Warn "Nothing to commit in ~/.claude."
                } else {
                    git commit -m "Initial Zaude-installed config" -q 2>$null
                    git remote add origin "https://github.com/$GhUser/zaude-claude-config.git" 2>$null
                    git push -u origin main -q 2>$null
                    Ok "Claude-config pushed."
                }
            } finally { Pop-Location }
        }
    } else {
        Warn "Skipping GitHub repo creation (gh not installed or not authenticated)."
    }

    Write-Host ""
    Write-Host "Zaude installed." -ForegroundColor Green
    Write-Host ""
    Write-Host "  Vault:         $VaultPath"
    Write-Host "  Claude config: $ClaudeDir"
    Write-Host "  Config file:   $Config"
    Write-Host "  First project: $ProjectSlug (mapped to cwd basename `"$ProjectCwdBase`")"
    Write-Host ""
    Write-Host "Next:"
    Write-Host "  1. Open a new Claude Code session in $ProjectCwd"
    Write-Host "  2. The initial system reminder should include '=== VAULT CONTEXT FOR $ProjectSlug ==='"
    Write-Host "  3. Run /start to confirm Zaude is loaded"
    Write-Host "  4. Start shipping"
    Write-Host ""
    Write-Host "Don't vibe code. Zaude code." -ForegroundColor Cyan

} finally {
    Remove-Item -Path $TmpDir -Recurse -Force -ErrorAction SilentlyContinue
}
