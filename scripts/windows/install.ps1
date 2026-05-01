param(
    [string]$ApiKey,
    [string]$Hotkey = "f10",
    [switch]$Autostart
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir "..\.."))
$VenvDir = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvDir "Scripts\python.exe"

Set-Location $ProjectRoot

function Get-CompatiblePython {
    $candidates = @(
        @{ Kind = "py"; Args = @("-3.11") },
        @{ Kind = "py"; Args = @("-3.12") }
    )

    foreach ($candidate in $candidates) {
        $cmd = Get-Command $candidate.Kind -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                $result = & $candidate.Kind @($candidate.Args) -c "import sys; print(sys.executable)" 2>$null
            } catch {
                $result = $null
            }
            if ($LASTEXITCODE -eq 0 -and $result) {
                return $result.Trim()
            }
        }
    }

    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        & uv python install 3.11
        $result = & uv python find 3.11
        if ($LASTEXITCODE -eq 0 -and $result) {
            return $result.Trim()
        }
    }

    throw "Python 3.11/3.12 is required for this ASR stack. Install Python 3.11 or install uv."
}

if (Test-Path -LiteralPath $PythonExe) {
    $venvVersion = & $PythonExe -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
    if ($venvVersion -notin @("3.11", "3.12")) {
        $projectFullPath = [System.IO.Path]::GetFullPath($ProjectRoot)
        $venvFullPath = [System.IO.Path]::GetFullPath($VenvDir)
        if (-not $venvFullPath.StartsWith($projectFullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove venv outside project: $venvFullPath"
        }
        Remove-Item -LiteralPath $VenvDir -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $PythonExe)) {
    $BasePython = Get-CompatiblePython
    & $BasePython -m venv $VenvDir
}

& $PythonExe -m pip install --upgrade pip setuptools wheel

& $PythonExe -m pip install --upgrade -r (Join-Path $ProjectRoot "requirements.txt")

if ($ApiKey) {
    $envContent = @(
        "TRANSCRIPTION_API_KEY=$ApiKey",
        "TRANSCRIPTION_MODEL=openai/whisper-1",
        "TRANSCRIPTION_FALLBACK_MODEL=",
        "TRANSCRIPTION_API_URL=https://openrouter.ai/api/v1/audio/transcriptions",
        "TRANSCRIPTION_TIMEOUT=120",
        "TRANSCRIPTION_LANGUAGE=ru",
        "TRANSCRIPTION_PROMPT=Transcribe this Russian speech to plain text. Return only the transcript.",
        "TRANSCRIPTION_REFERER=https://localhost/dictator",
        "TRANSCRIPTION_TITLE=Dictator",
        "DICTATOR_HOTKEY=$Hotkey",
        "DICTATOR_LOG_FILE=runtime/dictator.log"
    )
    Set-Content -LiteralPath (Join-Path $ProjectRoot ".env") -Value $envContent -Encoding UTF8
}

if ($Autostart) {
    $RunScript = Join-Path $ProjectRoot "scripts\windows\run.ps1"
    $StartupDir = [Environment]::GetFolderPath("Startup")
    $OldStartupScript = Join-Path $StartupDir "DictatorParakeet.vbs"
    $StartupScript = Join-Path $StartupDir "DictatorWhisper.vbs"
    if (Test-Path -LiteralPath $OldStartupScript) {
        Remove-Item -LiteralPath $OldStartupScript -Force
    }
    $vbs = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$RunScript""", 0, False
"@
    Set-Content -LiteralPath $StartupScript -Value $vbs -Encoding Unicode
}

Write-Host ""
Write-Host "Install complete."
Write-Host "Run: powershell -ExecutionPolicy Bypass -File .\scripts\windows\run.ps1"
Write-Host "Hotkey: $Hotkey"
