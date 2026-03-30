param(
  [string]$Version = $env:ROXANNE_VERSION,
  [string]$Repo = $(if ($env:ROXANNE_REPO) { $env:ROXANNE_REPO } else { "TylerIllman/Roxanne" }),
  [switch]$NoOpen
)

$ErrorActionPreference = "Stop"

function Write-Info {
  param([string]$Message)
  Write-Host "[roxanne-install] $Message"
}

function Get-LatestTag {
  $release = Invoke-RestMethod -Uri "https://api.github.com/repos/$Repo/releases/latest"
  if (-not $release.tag_name) {
    throw "Could not determine the latest GitHub Release tag."
  }
  return [string]$release.tag_name
}

function Normalize-Tag {
  param([string]$Tag)
  if ([string]::IsNullOrWhiteSpace($Tag)) {
    return ""
  }
  if ($Tag.StartsWith("v")) {
    return $Tag
  }
  return "v$Tag"
}

$tag = Normalize-Tag $Version
if ([string]::IsNullOrWhiteSpace($tag)) {
  $tag = Get-LatestTag
}

$versionNumber = $tag.TrimStart("v")
$assetName = "Roxanne-$versionNumber-win-x64.exe"
$assetUrl = "https://github.com/$Repo/releases/download/$tag/$assetName"
$tempPath = Join-Path $env:TEMP $assetName

Write-Info "Downloading $assetName"
Invoke-WebRequest -Uri $assetUrl -OutFile $tempPath

Write-Info "Running installer"
Start-Process -FilePath $tempPath -Wait

if (-not $NoOpen.IsPresent -and -not $env:ROXANNE_NO_OPEN) {
  $candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Roxanne\Roxanne.exe"),
    (Join-Path $env:ProgramFiles "Roxanne\Roxanne.exe")
  )

  if (${env:ProgramFiles(x86)} -and $env:ProgramFiles -ne ${env:ProgramFiles(x86)}) {
    $candidates += (Join-Path ${env:ProgramFiles(x86)} "Roxanne\Roxanne.exe")
  }

  $installedPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($installedPath) {
    Write-Info "Opening Roxanne"
    Start-Process -FilePath $installedPath
  }
}

Write-Info "Done"
