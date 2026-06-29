param(
    [Parameter(Mandatory=$true)]
    [string]$InFile,
    [Parameter(Mandatory=$true)]
    [string]$OutFile
)

Write-Host "Input : $InFile"
Write-Host "Output: $OutFile"

# Load tool paths from tools_config.json (searching up from script directory)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$CfgDir = $ScriptDir
$ConfigFile = $null
while ($true) {
    $candidate = Join-Path $CfgDir "tools_config.json"
    if (Test-Path $candidate) { $ConfigFile = $candidate; break }
    $parent = Split-Path $CfgDir -Parent
    if ($parent -eq $CfgDir) { break }
    $CfgDir = $parent
}

if (-not $ConfigFile) {
    Write-Error "tools_config.json not found. Create a tools_config.json in the repository root (or a parent directory of this script)."
    exit 1
}

try {
    $cfg = Get-Content -Raw $ConfigFile | ConvertFrom-Json
} catch {
    Write-Error "Failed to parse $($ConfigFile): $_"
    exit 1
}

if (-not $cfg.ffmpeg -or -not $cfg.ffprobe -or -not $cfg.mkvmerge) {
    Write-Error "tools_config.json must contain keys: ffmpeg, ffprobe, mkvmerge"
    exit 1
}

$FFMPEG = $cfg.ffmpeg
$FFPROBE = $cfg.ffprobe
$MKVMERGE = $cfg.mkvmerge

if (-not (Test-Path $InFile)) {
    Write-Error "Input file not found: $InFile"
    exit 1
}

$HDR = $false
$DV = $false

# Detect HDR10/HLG via color properties
$colorInfo = & $FFPROBE -v quiet -select_streams v:0 `
    -show_entries stream=color_space,color_transfer,color_primaries `
    -of default=nw=1:nk=1 "$InFile" 2>$null

if ($colorInfo -match 'bt2020|smpte2084|arib-std-b67') {
    $HDR = $true
}

# Detect Dolby Vision
$dvInfo = & $FFPROBE -v quiet -select_streams v:0 `
    -show_entries stream=codec_name,side_data_list `
    -of json "$InFile" 2>$null

if ($dvInfo -match 'dolby_vision|dvhe|dvh1') {
    $DV = $true
}

# Detect resolution
$HEIGHT = & $FFPROBE -v quiet -select_streams v:0 `
    -show_entries stream=height `
    -of default=nw=1:nk=1 "$InFile" 2>$null
$HEIGHT = if ($HEIGHT -match '^\d+$') { [int]$HEIGHT } else { 0 }

$WIDTH = & $FFPROBE -v quiet -select_streams v:0 `
    -show_entries stream=width `
    -of default=nw=1:nk=1 "$InFile" 2>$null
$WIDTH = if ($WIDTH -match '^\d+$') { [int]$WIDTH } else { 0 }

$ORIG_BITRATE = & $FFPROBE -v quiet -select_streams v:0 `
    -show_entries stream=bit_rate `
    -of default=nw=1:nk=1 "$InFile" 2>$null
$ORIG_BITRATE = if ($ORIG_BITRATE -match '^\d+$') { [int]$ORIG_BITRATE } else { 0 }

# MKV often stores bitrate at container level only
if ($ORIG_BITRATE -eq 0) {
    $ORIG_BITRATE = & $FFPROBE -v quiet `
        -show_entries format=bit_rate `
        -of default=nw=1:nk=1 "$InFile" 2>$null
    $ORIG_BITRATE = if ($ORIG_BITRATE -match '^\d+$') { [int]$ORIG_BITRATE } else { 0 }
}

Write-Host "HDR detected:  $HDR"
Write-Host "Dolby Vision:  $DV"
Write-Host "Resolution:    ${WIDTH}x${HEIGHT}"
Write-Host "Orig bitrate:  $ORIG_BITRATE"

if (-not ($HDR -or $DV)) {
    Write-Warning "Input is not HDR/DV. No conversion needed."
    exit 0
}

# HDR/DV -> SDR tonemapping (CPU zscale + tonemap)
$VF = "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p"

# Use original bitrate if detected, fallback by resolution
if ($ORIG_BITRATE -gt 0) {
    $BITRATE = "${ORIG_BITRATE}"
    $MAXRATE = "${ORIG_BITRATE}"
    $BUFSIZE  = "$([int]($ORIG_BITRATE * 2))"
} elseif ($HEIGHT -ge 2160) {
    $BITRATE = "20M"; $MAXRATE = "20M"; $BUFSIZE = "40M"
} elseif ($HEIGHT -ge 1080) {
    $BITRATE = "9M";  $MAXRATE = "9M";  $BUFSIZE = "18M"
} else {
    $BITRATE = "5M";  $MAXRATE = "5M";  $BUFSIZE = "10M"
}

Write-Host "Using bitrate: $BITRATE"
Write-Host "Running ffmpeg..."

& $FFMPEG -y -hide_banner `
    -i "$InFile" `
    -map 0 `
    -vf "$VF" `
    -c:v h264_nvenc -preset p5 -rc vbr `
    -b:v "$BITRATE" -maxrate "$MAXRATE" -bufsize "$BUFSIZE" `
    -c:a copy -c:s copy `
    -colorspace bt709 -color_primaries bt709 -color_trc bt709 `
    "$OutFile"

$code = $LASTEXITCODE
Write-Host "ffmpeg exit code: $code"
exit $code
