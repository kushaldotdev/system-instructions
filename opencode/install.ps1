#Requires -Version 5.1
param(
    [switch]$Global,
    [string]$Project,
    [switch]$Lsp,
    [switch]$NoPrompt
)

$ErrorActionPreference = 'Stop'

$ScriptDir = $PSScriptRoot
$HomeDir = $env:USERPROFILE

$Mode = ''
$ProjectDir = ''
$LspEnabled = $Lsp

Write-Host "============================================"
Write-Host "  opencode Custom Modes Installer"
Write-Host "============================================"
Write-Host ""

# --- mode ---
if (-not $Global -and [string]::IsNullOrEmpty($Project)) {
    Write-Host "Install mode (default: global):"
    Write-Host "  g) Global -- applies to ALL projects on this machine"
    Write-Host "  p) Project -- installs in a specific project"
    Write-Host "  b) Both"
    Write-Host "  q) Quit"
    $mc = Read-Host "Choice (g/p/b/q) [default: g]"
    switch -regex ($mc) {
        '^$' { $Mode = 'global' }
        '^[gG]$' { $Mode = 'global' }
        '^[pP]$' { $Mode = 'project' }
        '^[bB]$' { $Mode = 'both' }
        '^[qQ]$' { exit 0 }
        default { Write-Host "Invalid"; exit 1 }
    }
} elseif ($Global) {
    $Mode = 'global'
} elseif (-not [string]::IsNullOrEmpty($Project)) {
    $Mode = 'project'
    $ProjectDir = $Project
}

# --- LSP for opencode (only if interactive and not already set by arg) ---
if (-not $NoPrompt -and [Environment]::UserInteractive -and -not $Lsp) {
    Write-Host ""
    Write-Host "Enable LSP for opencode? (Y/n):"
    Write-Host "  LSP provides diagnostics and symbol intelligence when reading files."
    Write-Host "  Note: adds small token overhead (diagnostic messages per file)."
    $lspInput = Read-Host "Choice (Y/n) [default: Y]"
    if ($lspInput -match '^[nN]') { $LspEnabled = $false } else { $LspEnabled = $true }
}

# --- project dir ---
if ($Mode -eq 'project' -or $Mode -eq 'both') {
    if ([string]::IsNullOrEmpty($ProjectDir)) {
        $ProjectDir = Read-Host "Project directory (or Enter for current)"
        if ([string]::IsNullOrEmpty($ProjectDir)) {
            $ProjectDir = (Get-Location).Path
        }
    }
    if (-not (Test-Path -Path $ProjectDir -PathType Container)) {
        Write-Host "Invalid directory: $ProjectDir"
        exit 1
    }
    $ProjectDir = (Resolve-Path -Path $ProjectDir).Path
    Write-Host "Project: $ProjectDir"
    Write-Host ""
}

# --- Helpers ---
Function Test-GlobalInstalled {
    return ((Test-Path -Path "$HomeDir\.config\opencode\opencode.jsonc") -or (Test-Path -Path "$HomeDir\.config\opencode\opencode.json"))
}

Function Install-To {
    param([string]$Target, [string]$Label)

    Write-Host ""
    Write-Host "  -- opencode custom modes ($Label)"
    Write-Host "     target: $Target"

    $agentsDir = Join-Path $Target "agents"
    New-Item -Path $agentsDir -ItemType Directory -Force | Out-Null

    $instructionsSrc = Join-Path $ScriptDir "instructions.md"
    $instructionsDst = Join-Path $Target "instructions.md"
    Copy-Item -Path $instructionsSrc -Destination $instructionsDst -Force

    $agentsSrc = Join-Path $ScriptDir "agents\*.md"
    Copy-Item -Path $agentsSrc -Destination $agentsDir -Force

    Write-Host "    [copy]   instructions.md, agents/{plan,test,build,review,general}.md"

    $config = Join-Path $Target "opencode.jsonc"

    $agentsJson = Join-Path $ScriptDir "agents.json"
    $agentDefsObj = Get-Content -Path $agentsJson -Raw | ConvertFrom-Json

    $firstBrace = -1
    if (Test-Path -Path $config -PathType Leaf) {
        $raw = Get-Content -Path $config -Raw
        $firstBrace = $raw.IndexOf('{')
    }

    if ($firstBrace -ge 0) {
        $content = $raw
        $changed = $false

        # 1. Update instructions
        $normPath = $instructionsDst.Replace('\', '/')
        if ($content -notmatch [regex]::Escape($normPath)) {
            $instMatch = [regex]::Match($content, '"instructions"\s*:\s*\[')
            if ($instMatch.Success) {
                $pos = $instMatch.Index + $instMatch.Length
                $content = $content.Substring(0, $pos) + "`r`n    `"$normPath`"," + $content.Substring($pos)
                $changed = $true
            } else {
                $pos = $firstBrace + 1
                $content = $content.Substring(0, $pos) + "`r`n  `"instructions`": [`r`n    `"$normPath`"`r`n  ]," + $content.Substring($pos)
                $changed = $true
            }
        }

        # 2. Update lsp
        if ($LspEnabled) {
            $lspMatch = [regex]::Match($content, '"lsp"\s*:\s*(true|false)')
            if ($lspMatch.Success) {
                $content = $content.Substring(0, $lspMatch.Index) + "`"lsp`": true" + $content.Substring($lspMatch.Index + $lspMatch.Length)
                $changed = $true
            } else {
                $pos = $firstBrace + 1
                $content = $content.Substring(0, $pos) + "`r`n  `"lsp`": true," + $content.Substring($pos)
                $changed = $true
            }
        } else {
            $lspMatch = [regex]::Match($content, '"lsp"\s*:\s*(true|false),?\s*')
            if ($lspMatch.Success) {
                $content = $content.Substring(0, $lspMatch.Index) + $content.Substring($lspMatch.Index + $lspMatch.Length)
                $changed = $true
            }
        }

        # 3. Update agent
        $agentsRaw = Get-Content -Path $agentsJson -Raw
        $agentMatch = [regex]::Match($content, '"agent"\s*:\s*\{')
        if ($agentMatch.Success) {
            $braceStart = $content.IndexOf('{', $agentMatch.Index)
            $depth = 0
            $braceEnd = -1
            for ($i = $braceStart; $i -lt $content.Length; $i++) {
                $c = $content[$i]
                if ($c -eq '{') { $depth++ }
                elseif ($c -eq '}') {
                    $depth--
                    if ($depth -eq 0) {
                        $braceEnd = $i
                        break
                    }
                }
            }
            if ($braceEnd -gt 0) {
                $newAgentBlock = "`"agent`": " + $agentsRaw.Trim()
                $content = $content.Substring(0, $agentMatch.Index) + $newAgentBlock + $content.Substring($braceEnd + 1)
                $changed = $true
            }
        } else {
            $pos = $firstBrace + 1
            $content = $content.Substring(0, $pos) + "`r`n  `"agent`": " + $agentsRaw.Trim() + "," + $content.Substring($pos)
            $changed = $true
        }

        if ($changed) {
            Set-Content -Path $config -Value $content -Encoding UTF8
            Write-Host "    [update] $config"
        } else {
            Write-Host "    [skip]   $config (no changes needed)"
        }
    } else {
        $normPath = $instructionsDst.Replace('\', '/')
        $agentsRaw = Get-Content -Path $agentsJson -Raw
        $newJson = @(
            "{"
            "  `"`$schema`": `"https://opencode.ai/config.json`","
            "  `"instructions`": ["
            "    `"$normPath`""
            "  ],"
        )
        if ($LspEnabled) {
            $newJson += "  `"lsp`": true,"
        }
        $newJson += "  `"agent`": " + $agentsRaw.Trim()
        $newJson += "}"
        $newJsonString = $newJson -join "`r`n"
        Set-Content -Path $config -Value $newJsonString -Encoding UTF8
        Write-Host "    [create] $config"
    }
}

# === Global install ===
Function Install-Global {
    Install-To -Target "$HomeDir\.config\opencode" -Label "global"

    # WSL: also install to WSL distro home directories if accessible
    try {
        $output = wsl -l -q 2>$null
        if ($LASTEXITCODE -eq 0) {
            $wslDistros = $output -split "[\r\n\0]+" | Where-Object { $_ -match '\S' } | ForEach-Object { $_.Trim() }
        } else {
            $wslDistros = @()
        }
    } catch {
        $wslDistros = @()
    }
    foreach ($distro in $wslDistros) {
        $wslBase = "\\wsl.localhost\$distro\home"
        if (Test-Path -Path $wslBase) {
            $users = Get-ChildItem -Path $wslBase -Directory -ErrorAction SilentlyContinue
            foreach ($user in $users) {
                $wslTarget = Join-Path $user.FullName ".config\opencode"
                Install-To -Target $wslTarget -Label "WSL ($distro\$($user.Name))"
            }
        }
    }
}

# === Project install ===
Function Install-Project {
    param([string]$Target)

    if (Test-GlobalInstalled) {
        Write-Host ""
        Write-Host "  -- opencode custom modes (project) -- SKIPPED (global already installed)"
        return
    }

    $opencodeDir = Join-Path $Target ".opencode"
    Install-To -Target $opencodeDir -Label "project"
}

# === Execute ===
$runGlobal = ($Mode -eq 'global' -or $Mode -eq 'both')
$runProject = ($Mode -eq 'project' -or $Mode -eq 'both')

if ($runGlobal) { Install-Global }
if ($runProject) { Install-Project -Target $ProjectDir }

# Disable Claude Code compatibility in OpenCode by default
if (-not $NoPrompt -and ($runGlobal) -and ([Environment]::UserInteractive)) {
    Write-Host ""
    Write-Host "Disable Claude Code compatibility prompt in OpenCode? (Y/n) [default: Y]:"
    Write-Host "  Recommended to avoid conflicting rule definitions between agents."
    $disableInput = Read-Host "Choice (Y/n) [default: Y]"
    if ($disableInput -match '^[nN]') {
        Write-Host "  Enabling Claude Code compatibility for OpenCode (cleaning up old configs)..."
        [System.Environment]::SetEnvironmentVariable('OPENCODE_DISABLE_CLAUDE_CODE_PROMPT', $null, 'User')
        Write-Host "    Deleted User environment variable: OPENCODE_DISABLE_CLAUDE_CODE_PROMPT"
    } else {
        Write-Host "  Disabling Claude Code compatibility for OpenCode in Windows environment..."
        [System.Environment]::SetEnvironmentVariable('OPENCODE_DISABLE_CLAUDE_CODE_PROMPT', 'true', 'User')
        Write-Host "    Set User environment variable: OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=true"
    }
}

Write-Host ""
Write-Host "========================="
Write-Host "  Done!"
Write-Host "  Please quit and restart opencode for changes to take effect."
if ($runGlobal) { Write-Host "  Global: $HomeDir\.config\opencode\" }
if ($runProject) { Write-Host "  Project: $ProjectDir\.opencode\" }
$lspStatus = if ($LspEnabled) { "enabled" } else { "disabled" }
Write-Host "  LSP: $lspStatus"
Write-Host "========================="
