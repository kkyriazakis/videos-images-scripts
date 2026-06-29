$ErrorActionPreference = "Stop"

# --- HARD-CODED FOLDERS (EDIT THESE) ---
$SRC_ROOT = "F:\torr"
$DST_ROOT = "F:\torr\no_hdr"
# ---------------------------------------

$THIS_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$REMOVE_HDR_SCRIPT = Join-Path $THIS_DIR "remove_hdr.ps1"

if (-not (Test-Path $REMOVE_HDR_SCRIPT)) {
    Write-Error "remove_hdr.ps1 not found at: $REMOVE_HDR_SCRIPT"
    exit 1
}

Write-Host "Source:      $SRC_ROOT"
Write-Host "Destination: $DST_ROOT"

# Find video files and process them
Get-ChildItem -Path $SRC_ROOT -Recurse -Include *.mkv,*.mp4,*.mov -File | ForEach-Object {
    $IN = $_.FullName

    # Relative path from source root
    $SRC_ROOT_FULL = (Resolve-Path $SRC_ROOT).Path
    $REL = $IN.Substring($SRC_ROOT_FULL.Length).TrimStart('\', '/')

    # Ensure .mkv extension in destination
    $OUT_REL = [System.IO.Path]::ChangeExtension($REL, ".mkv")
    $OUT = Join-Path $DST_ROOT $OUT_REL

    $OUT_DIR = Split-Path -Parent $OUT
    if (-not (Test-Path $OUT_DIR)) {
        New-Item -ItemType Directory -Path $OUT_DIR -Force | Out-Null
    }

    Write-Host "=== Removing HDR ==="
    Write-Host "IN : $IN"
    Write-Host "OUT: $OUT"
    Write-Host "===================="

    & $REMOVE_HDR_SCRIPT "$IN" "$OUT"

    if ($LASTEXITCODE -ne 0) {
        Write-Warning "HDR removal failed for: $IN"
    }
}

Write-Host "Folder HDR removal complete!"
