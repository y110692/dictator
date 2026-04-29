param(
    [string]$Hotkey = "",
    [switch]$Lazy,
    [switch]$NoTray
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = [System.IO.Path]::GetFullPath((Join-Path $ScriptDir "..\.."))
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "Virtual environment not found. Run scripts\windows\install.ps1 first."
}

$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path -LiteralPath $EnvFile) {
    Get-Content -LiteralPath $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }

        $parts = $line.Split("=", 2)
        $name = $parts[0].Trim().Trim([char]0xFEFF)
        $value = $parts[1].Trim()
        if ($value.Length -ge 2 -and $value[0] -eq $value[$value.Length - 1] -and ($value[0] -eq '"' -or $value[0] -eq "'")) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if ($name -and -not [Environment]::GetEnvironmentVariable($name, "Process")) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

$argsList = @()
if ($Hotkey) { $argsList += @("--hotkey", $Hotkey) }
if ($Lazy) { $argsList += "--lazy" }
if ($NoTray) { $argsList += "--no-tray" }

& $PythonExe (Join-Path $ProjectRoot "src\windows\dictator_app.py") @argsList
