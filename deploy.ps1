<#
.SYNOPSIS
    Copies this project onto a connected Matrix Portal M4's MATRIXBOOT drive.

.DESCRIPTION
    Finds the CIRCUITPY volume, copies code.py + every project module +
    settings.toml from src/ onto it, and (optionally) runs circup to
    install/update the required libraries into lib/ on the device.

.PARAMETER InstallLibs
    Also run `circup install` for the libraries this project needs.
    Requires circup (`pip install circup`) and a board already running
    CircuitPython.

.EXAMPLE
    .\deploy.ps1
    .\deploy.ps1 -InstallLibs
#>
param(
    [switch]$InstallLibs
)

$ErrorActionPreference = "Stop"

$SrcDir = Join-Path $PSScriptRoot "src"

$ProjectFiles = @(
    "code.py",
    "config.py",
    "tz.py",
    "rtc_manager.py",
    "sensors.py",
    "brightness.py",
    "display_modes.py",
    "wifi_manager.py",
    "ha_client.py",
    "settings.toml"
)

$RequiredLibs = @(
    "adafruit_matrixportal",
    "adafruit_ds3231",
    "adafruit_ahtx0",
    "adafruit_bh1750",
    "adafruit_display_text",
    "adafruit_requests",
    "adafruit_connection_manager",
    "adafruit_ntp"
)

$vol = Get-Volume -ErrorAction SilentlyContinue | Where-Object { $_.FileSystemLabel -eq "CIRCUITPY" }
if (-not $vol) {
    Write-Error "No CIRCUITPY drive found. Plug in the Matrix Portal M4 (already running CircuitPython) and try again. (If you see a MATRIXBOOT drive instead, the board is in UF2 bootloader mode -- tap reset once to boot into CircuitPython.)"
}
$drive = "$($vol.DriveLetter):"
Write-Output "Found CIRCUITPY at $drive"

$settingsPath = Join-Path $SrcDir "settings.toml"
$settingsContent = Get-Content $settingsPath -Raw
if ($settingsContent -match 'your_ssid' -or $settingsContent -match 'your_password' -or $settingsContent -match 'your_long_lived_access_token') {
    Write-Warning "settings.toml still has placeholder WIFI_SSID/WIFI_PASSWORD/HA_TOKEN values. Edit settings.toml before deploying, or the clock will try to associate to a literal network named 'your_ssid'."
}

foreach ($f in $ProjectFiles) {
    $src = Join-Path $SrcDir $f
    if (-not (Test-Path $src)) {
        Write-Warning "Skipping $f -- not found in $SrcDir"
        continue
    }
    Copy-Item -Path $src -Destination (Join-Path $drive $f) -Force
    Write-Output "Copied $f"
}

if ($InstallLibs) {
    if (-not (Get-Command circup -ErrorAction SilentlyContinue)) {
        Write-Warning "circup not found on PATH. Install it with: pip install circup"
    } else {
        Write-Output "Running circup install for required libraries..."
        & circup --path $drive install @RequiredLibs
    }
}

Write-Output "Deploy complete. Watch the serial console for boot output."
