#Requires -Version 5.1
param(
    [switch]$Global,
    [string]$Project,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# --- paths ---
$ScriptDir = $PSScriptRoot
$CentralRoot = Split-Path -Parent $ScriptDir
$Sysp = Join-Path $CentralRoot '.agents\SYSTEM_PROMPT.md'
$Rules = Join-Path $CentralRoot '.agents\RULES.md'
$Inst = Join-Path $CentralRoot 'INSTRUCTIONS.md'
$CheckpointTemplate = Join-Path $CentralRoot '.agents\CHECKPOINT.md.template'
$HomeDir = $env:USERPROFILE

$Mode = ''
$ProjectDir = ''
$Format = ''
$Ocfile1 = ''
$Ocfile2 = ''

Write-Host "============================================"
Write-Host "  .agents Workflow Installer"
Write-Host "  Central: $CentralRoot\.agents\"
Write-Host "============================================"
Write-Host ""

# --- mode ---
if (-not $Global -and [string]::IsNullOrEmpty($Project)) {
    Write-Host "Install mode:"
    Write-Host "  g) Global -- applies to ALL projects on this machine"
    Write-Host "  p) Project -- bridges in a specific project"
    Write-Host "  b) Both"
    Write-Host "  q) Quit"
    $mc = Read-Host "Choice (g/p/b/q)"
    switch -regex ($mc) {
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

# --- format ---
Write-Host "Instructions format:"
Write-Host "  m) Modular -- SYSTEM_PROMPT.md + RULES.md (two files)"
Write-Host "  s) Standalone -- INSTRUCTIONS.md (single merged file)"
$fmt = Read-Host "Choice (m/s)"
switch -regex ($fmt) {
    '^[mM]$' {
        $Format = 'modular'
        $Ocfile1 = $Sysp
        $Ocfile2 = $Rules
    }
    '^[sS]$' {
        $Format = 'standalone'
        $Ocfile1 = $Inst
        $Ocfile2 = ''
    }
    default { Write-Host "Invalid"; exit 1 }
}

# --- LSP for opencode ---
Write-Host ""
Write-Host "Enable LSP for opencode? (y/N):"
Write-Host "  LSP provides diagnostics and symbol intelligence when reading files."
Write-Host "  Note: adds small token overhead (diagnostic messages per file)."
$lspInput = Read-Host "Choice (y/N)"
if ($lspInput -match '^[yY]') { $LspEnabled = $true } else { $LspEnabled = $false }

# --- tool selection ---
Write-Host ""
Write-Host "Select tools to configure (comma-separated, a for all):"
Write-Host "  1) opencode"
Write-Host "  2) claude-code"
Write-Host "  3) antigravity"
Write-Host "  4) codex"
Write-Host "  5) cline"
Write-Host "  6) kilo-code"
Write-Host "  a) all"
Write-Host "  q) quit"
$selInput = Read-Host "> "
if ($selInput -eq 'q') { exit 0 }
if ($selInput -eq 'a') { $selInput = '1,2,3,4,5,6' }
$selection = $selInput -replace '\s+', '' -split ','
if ($selection.Count -eq 0 -or ($selection.Count -eq 1 -and [string]::IsNullOrEmpty($selection[0]))) {
    Write-Host "No tools selected."
    exit 0
}

Function Write-InstructBridge {
    param([string]$File, [string]$Label)
    $dir = Split-Path $File -Parent
    New-Item -Path $dir -ItemType Directory -Force | Out-Null

    # Check existing file (preserve custom content unless -Force)
    if (Test-Path -Path $File -PathType Leaf) {
        $firstLine = Get-Content -Path $File -First 1
        if ($firstLine -ne '# AI Behavior Rules' -and -not $Force) {
            Write-Host "    [skip]  $File (custom content exists, use -Force to overwrite)"
            return
        }
    }

    if ($Format -eq 'modular') {
        # Copy RULES.md and CHECKPOINT.md.template (not SYSTEM_PROMPT.md -- it IS the file)
        Copy-Item -Path $Rules -Destination "$dir\RULES.md" -Force
        Copy-Item -Path $CheckpointTemplate -Destination "$dir\CHECKPOINT.md.template" -Force
        # Write SYSP content with marker header + path substitution
        $content = "# AI Behavior Rules`r`n" + ((Get-Content -Path $Sysp -Raw) -replace '\.agents/RULES\.md', "$dir\RULES.md")
        $content = $content -replace '\.agents/CHECKPOINT\.md\.template', "$dir\CHECKPOINT.md.template"
        Set-Content -Path $File -Value $content -Encoding UTF8
    } else {
        # Write INST content with marker header (fully self-contained)
        $content = "# AI Behavior Rules`r`n" + (Get-Content -Path $Inst -Raw)
        Set-Content -Path $File -Value $content -Encoding UTF8
    }
    Write-Host "    [write] $File"
    # Clean up any old SYSTEM_PROMPT.md copy that is no longer needed
    $old = Join-Path $dir 'SYSTEM_PROMPT.md'
    if (Test-Path -Path $old) { Remove-Item -Path $old -Force }
}

Function Write-JsoncConfig {
    param([string]$Target, [string]$Filename, [string]$Label, [bool]$AddLsp = $false)
    $json = Join-Path -Path $Target -ChildPath $Filename

    $syspDest = Join-Path -Path $Target -ChildPath 'SYSTEM_PROMPT.md'
    $rulesDest = Join-Path -Path $Target -ChildPath 'RULES.md'
    $checkpointDest = Join-Path -Path $Target -ChildPath 'CHECKPOINT.md.template'
    Copy-Item -Path $Sysp -Destination $syspDest -Force
    Copy-Item -Path $Rules -Destination $rulesDest -Force
    Copy-Item -Path $CheckpointTemplate -Destination $checkpointDest -Force
    Write-Host "    [copy]   $syspDest, $rulesDest, $checkpointDest"

    (Get-Content $syspDest -Raw) -replace '\.agents/RULES\.md', $rulesDest | Set-Content $syspDest -NoNewline
    (Get-Content $syspDest -Raw) -replace '\.agents/CHECKPOINT\.md\.template', $checkpointDest | Set-Content $syspDest -NoNewline

    $localQuoted = "`"$($syspDest.Replace('\', '\\'))`""
    $permPathFwd = ($Target.Replace('\', '/') + '/*.md')
    $permPathBwd = ($Target + '\*.md')

    $extDirPattern = ""
    if ($Label -eq "global") {
        $toolName = $Filename -replace '\.jsonc$', ''
        $extDirPattern = "~/.config/$toolName/**"
    }

    if (Test-Path -Path $json -PathType Leaf) {
        $content = Get-Content -Path $json -Raw
        $changed = $false

        if ($content -match '"instructions"\s*:\s*\[[^\]]*"[A-Za-z]:\\(?!\\)') {
            $start = $content.IndexOf('"instructions"')
            $end = $content.IndexOf(']', $start) + 1
            $newBlock = "`"instructions`": [`n    $localQuoted`n  ]"
            $content = $content.Substring(0, $start) + $newBlock + $content.Substring($end)
            $changed = $true
        } elseif ($content -match '"instructions"\s*:\s*\[[^\]]*RULES\.md') {
            $start = $content.IndexOf('"instructions"')
            $end = $content.IndexOf(']', $start) + 1
            $newBlock = "`"instructions`": [`n    $localQuoted`n  ]"
            $content = $content.Substring(0, $start) + $newBlock + $content.Substring($end)
            $changed = $true
        } elseif (-not ($content -match '"instructions"')) {
            $lastBrace = $content.LastIndexOf('}')
            $before = $content.Substring(0, $lastBrace).TrimEnd()
            $after = $content.Substring($lastBrace)
            $newBlock = "`"instructions`": [`n    $localQuoted`n  ]"
            if ($before -match ',$') {
                $content = $before + "`n  " + $newBlock + "`n" + $after
            } else {
                $content = $before + ",`n  " + $newBlock + "`n" + $after
            }
            $changed = $true
        }

        $hasPerm = $content.Contains($permPathFwd) -or $content.Contains($permPathBwd)
        if (-not $hasPerm) {
            $permStart = $content.IndexOf('"permission"')
            if ($permStart -ge 0) {
                $braceStart = $content.IndexOf('{', $permStart)
                if ($braceStart -ge 0) {
                    $depth = 0; $insertPos = -1
                    for ($i = $braceStart; $i -lt $content.Length; $i++) {
                        $c = $content[$i]
                        if ($c -eq '{') { $depth++ }
                        elseif ($c -eq '}') { $depth--; if ($depth -eq 0) { $insertPos = $i; break } }
                    }
                    if ($insertPos -gt 0) {
                        $before = $content.Substring(0, $insertPos).TrimEnd()
                        $after = $content.Substring($insertPos)
                        $readRule = "`"read`": {`n        `"$permPathFwd`": `"allow`"`n      }"
                        if ($before -match ',$') {
                            $content = $before + "`n      " + $readRule + "`n    " + $after
                        } else {
                            $content = $before + ",`n      " + $readRule + "`n    " + $after
                        }
                        $changed = $true
                    }
                }
            } else {
                $lastBrace = $content.LastIndexOf('}')
                $before = $content.Substring(0, $lastBrace).TrimEnd()
                $after = $content.Substring($lastBrace)
                if ($extDirPattern) {
                    $permBlock = "`"permission`": {`n      `"read`": {`n        `"$permPathFwd`": `"allow`"`n      },`n      `"external_directory`": {`n        `"$extDirPattern`": `"allow`"`n      }`n    }"
                } else {
                    $permBlock = "`"permission`": {`n      `"read`": {`n        `"$permPathFwd`": `"allow`"`n      }`n    }"
                }
                if ($before -match ',$') {
                    $content = $before + "`n  " + $permBlock + "`n" + $after
                } else {
                    $content = $before + ",`n  " + $permBlock + "`n" + $after
                }
                $changed = $true
            }
        }

        if ($extDirPattern -and (-not $content.Contains('"external_directory"'))) {
            $permStart = $content.IndexOf('"permission"')
            if ($permStart -ge 0) {
                $braceStart = $content.IndexOf('{', $permStart)
                if ($braceStart -ge 0) {
                    $depth = 0; $insertPos = -1
                    for ($i = $braceStart; $i -lt $content.Length; $i++) {
                        $c = $content[$i]
                        if ($c -eq '{') { $depth++ }
                        elseif ($c -eq '}') { $depth--; if ($depth -eq 0) { $insertPos = $i; break } }
                    }
                    if ($insertPos -gt 0) {
                        $before = $content.Substring(0, $insertPos).TrimEnd()
                        $after = $content.Substring($insertPos)
                        $extDirRule = "`"external_directory`": {`n        `"$extDirPattern`": `"allow`"`n      }"
                        if ($before -match ',$') {
                            $content = $before + "`n      " + $extDirRule + "`n    " + $after
                        } else {
                            $content = $before + ",`n      " + $extDirRule + "`n    " + $after
                        }
                        $changed = $true
                    }
                }
            }
        }

        # --- fix lsp for opencode ---
        if ($AddLsp -and -not ($content -match '"lsp"\s*:\s*true')) {
            $permStart = $content.IndexOf('"permission"')
            if ($permStart -ge 0) {
                $before = $content.Substring(0, $permStart).TrimEnd()
                $after = $content.Substring($permStart)
                if ($before -match ',$') {
                    $content = $before + "`n  `"lsp`": true,`n  " + $after
                } else {
                    $content = $before + ",`n  `"lsp`": true,`n  " + $after
                }
                $changed = $true
            }
        }

        if ($changed) {
            Set-Content -Path $json -Value $content -Encoding UTF8
            Write-Host "    [update] $json"
        } else {
            Write-Host "    [ok]     $json"
        }
    } else {
        $lspLine = if ($AddLsp) { "`n  `"lsp`": true," } else { "" }
        $content = "{
  `"instructions`": [
    $localQuoted
  ],$lspLine
  `"permission`": {
    `"read`": {
      `"$permPathFwd`": `"allow`""
        if ($extDirPattern) {
            $content += "`n    },`n    `"external_directory`": {`n      `"$extDirPattern`": `"allow`"`n    }"
        } else {
            $content += "`n    }"
        }
        $content += "`n  }`n}"
        Set-Content -Path $json -Value $content -Encoding UTF8
        Write-Host "    [create] $json"
    }
}

Function New-DirectoryIfMissing {
    param([string]$Path)
    if (-not (Test-Path -Path $Path -PathType Container)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

Function Get-GlobalPath {
    param([int]$ToolNum)
    switch ($ToolNum) {
        1 { return "$HomeDir\.config\opencode\opencode.jsonc" }
        2 { return "$HomeDir\.claude\CLAUDE.md" }
        3 { return "$HomeDir\.gemini\GEMINI.md" }
        4 { return "$HomeDir\.codex\AGENTS.md" }
        5 { return "$HomeDir\Documents\Cline\Rules\000-system-instructions.md" }
        6 { return "$HomeDir\.config\kilo\kilo.jsonc" }
    }
    return ''
}

Function Test-GlobalInstalled {
    param([int]$ToolNum)
    $f = Get-GlobalPath -ToolNum $ToolNum
    return (Test-Path -Path $f)
}

Function Install-AntigravityProject {
    param([string]$Target)
    $rulesDir = Join-Path -Path $Target -ChildPath '.agent\rules'
    New-DirectoryIfMissing -Path $rulesDir
    $files = if ($Format -eq 'modular') { @('SYSTEM_PROMPT.md', 'RULES.md') } else { @('INSTRUCTIONS.md') }
    foreach ($f in $files) {
        $link = Join-Path -Path $rulesDir -ChildPath $f
        if (Test-Path -Path $link) {
            Write-Host "    [exists] $link"
        } else {
            $src = if ($f -eq 'INSTRUCTIONS.md') { $Inst } else { Join-Path -Path $CentralRoot -ChildPath ".agents\$f" }
            try {
                New-Item -ItemType SymbolicLink -Path $link -Target $src -ErrorAction Stop | Out-Null
                Write-Host "    [link]   $link -> $src"
            } catch {
                Copy-Item -Path $src -Destination $link -Force
                Write-Host "    [copy]   $link"
            }
        }
    }
}

Function Install-GlobalTool {
    param([int]$ToolNum)
    Write-Host ""
    switch ($ToolNum) {
        1 {
            Write-Host "  -- opencode (global)"
            New-DirectoryIfMissing -Path "$HomeDir\.config\opencode"
            Write-JsoncConfig -Target "$HomeDir\.config\opencode" -Filename "opencode.jsonc" -Label "global" -AddLsp $LspEnabled
        }
        2 {
            Write-Host "  -- claude-code (global)"
            New-DirectoryIfMissing -Path "$HomeDir\.claude"
            Write-InstructBridge -File "$HomeDir\.claude\CLAUDE.md" -Label "Claude Code (global)"
        }
        3 {
            Write-Host "  -- antigravity (global)"
            New-DirectoryIfMissing -Path "$HomeDir\.gemini"
            Write-InstructBridge -File "$HomeDir\.gemini\GEMINI.md" -Label "Antigravity (global)"
        }
        4 {
            Write-Host "  -- codex (global)"
            New-DirectoryIfMissing -Path "$HomeDir\.codex"
            Write-InstructBridge -File "$HomeDir\.codex\AGENTS.md" -Label "Codex (global)"
        }
        5 {
            Write-Host "  -- cline (global)"
            New-DirectoryIfMissing -Path "$HomeDir\Documents\Cline\Rules"
            Write-InstructBridge -File "$HomeDir\Documents\Cline\Rules\000-system-instructions.md" -Label "Cline (global)"
        }
        6 {
            Write-Host "  -- kilo-code (global)"
            New-DirectoryIfMissing -Path "$HomeDir\.config\kilo"
            Write-JsoncConfig -Target "$HomeDir\.config\kilo" -Filename "kilo.jsonc" -Label "global"
        }
    }
}

Function Install-ProjectTool {
    param([int]$ToolNum, [string]$Target)
    if (Test-GlobalInstalled -ToolNum $ToolNum) {
        $labels = @{1='opencode';2='claude-code';3='antigravity';4='codex';5='cline';6='kilo-code'}
        Write-Host ""
        Write-Host "  -- $($labels[$ToolNum]) (project) -- SKIPPED (global exists)"
        return
    }
    Write-Host ""
    switch ($ToolNum) {
        1 {
            Write-Host "  -- opencode (project)"
            Write-JsoncConfig -Target $Target -Filename "opencode.jsonc" -Label "project" -AddLsp $LspEnabled
        }
        2 {
            Write-Host "  -- claude-code (project)"
            Write-InstructBridge -File (Join-Path $Target 'CLAUDE.md') -Label "Project Instructions"
        }
        3 {
            Write-Host "  -- antigravity (project)"
            Install-AntigravityProject -Target $Target
        }
        4 {
            Write-Host "  -- codex (project)"
            Write-InstructBridge -File (Join-Path $Target 'AGENTS.md') -Label "Project Instructions"
        }
        5 {
            Write-Host "  -- cline (project)"
            Write-InstructBridge -File (Join-Path $Target '.clinerules') -Label "Project Instructions"
        }
        6 {
            Write-Host "  -- kilo-code (project)"
            Write-JsoncConfig -Target $Target -Filename "kilo.jsonc" -Label "project"
        }
    }
}

# --- execute ---
$runGlobal = ($Mode -eq 'global' -or $Mode -eq 'both')
$runProject = ($Mode -eq 'project' -or $Mode -eq 'both')

foreach ($sel in $selection) {
    $num = 0
    if (-not [int]::TryParse($sel, [ref]$num)) { continue }
    if ($num -lt 1 -or $num -gt 6) { continue }

    if ($runGlobal) { Install-GlobalTool -ToolNum $num }
    if ($runProject) { Install-ProjectTool -ToolNum $num -Target $ProjectDir }
}

# Disable Claude Code compatibility in OpenCode by default
if ($selection -contains '1') {
    Write-Host ""
    Write-Host "Disable Claude Code compatibility prompt in OpenCode? (Y/n):"
    Write-Host "  Recommended to avoid conflicting rule definitions between agents."
    $disableInput = Read-Host "Choice (Y/n)"
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
if ($runGlobal) { Write-Host "  Global bridges installed" }
if ($runProject) { Write-Host "  Project bridges in $ProjectDir" }
Write-Host "  Format: $Format"
$lspStatus = if ($LspEnabled) { "enabled for opencode" } else { "disabled" }
Write-Host "  LSP: $lspStatus"
Write-Host "========================="
