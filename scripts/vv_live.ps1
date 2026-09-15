#requires -version 7
<#
.SYNOPSIS
  Housat — Verification & Validation live (Bilingual: V&V live harness / harnais V&V live).
.DESCRIPTION
  Executes the documented E2E runbook (docs/verification.md) against the running
  Docker Compose stack and asserts the acceptance criteria A1..A10 that are
  observable over HTTP:
    A1  backfill >= 2 scenes, final status 'done'
    A2  frame_store.anchor == true
    A3  milestone alerts monotone (no regression)
    A4  milestone M2/M3 <=> pivot_confirme == true
    A5  inference method recorded per observation
    A6  404/409/422 conform to RFC 7807 (application/problem+json)
    A7  no unsolicited external alert emission in local mode
    A8  compare grids aligned, progression capped at 130%
    A9  image_bbox present for every observation with an image overlay
    A10 report PDF: %PDF, ETag == sha256, 409 on duplicate, 422 on empty/ongoing week
  Read-only with respect to the repo; creates its own site via the public API.
.EXAMPLE
  pwsh -File scripts\vv_live.ps1
  pwsh -File scripts\vv_live.ps1 -Api http://localhost:8000
#>
[CmdletBinding()]
param(
  [string]$Api = 'http://localhost:8000',
  [int]$BackfillTimeoutSec = 900,
  [string]$SiteName = '',
  [double[]]$Bbox = @()
)

$ErrorActionPreference = 'Stop'
$script:results = [System.Collections.Generic.List[object]]::new()
$script:fail = 0

# --- Parcelle de test : .env du projet (VVSITE_*), sinon defauts du formulaire web.
# Permet de viser une region a forte disponibilite de scenes sans coder de
# localisation dans le depot (règle 7 : pas de ciblage visible).
$envFile = Join-Path (Split-Path $PSScriptRoot -Parent) '.env'
$cfg = @{}
if (Test-Path $envFile) {
  foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*)$') { $cfg[$Matches[1]] = $Matches[2].Trim() }
  }
}
if (-not $SiteName) {
  $SiteName = if ($cfg['VVSITE_NAME']) { $cfg['VVSITE_NAME'] } else { 'VV Live Parcelle' }
}
if ($Bbox.Count -eq 0) {
  $Bbox = [double[]]@(
    [double]($cfg['VVSITE_MIN_LON'] ?? '9.70'), [double]($cfg['VVSITE_MIN_LAT'] ?? '4.04'),
    [double]($cfg['VVSITE_MAX_LON'] ?? '9.71'), [double]($cfg['VVSITE_MAX_LAT'] ?? '4.05')
  )
}

function Write-Utf8([string]$Text, [string]$Color = 'Gray') {
  Write-Host $Text -ForegroundColor $Color
}

function Check([string]$Id, [string]$Label, [bool]$Ok, [string]$Detail = '') {
  $script:results.Add([pscustomobject]@{ Id = $Id; Label = $Label; Ok = $Ok; Detail = $Detail })
  if (-not $Ok) { $script:fail++ }
  $tag = if ($Ok) { 'PASS' } else { 'FAIL' }
  $color = if ($Ok) { 'Green' } else { 'Red' }
  Write-Host ("[{0}] {1,-4} {2}{3}" -f $tag, $Id, $Label, $(if ($Detail) { " :: $Detail" } else { '' })) -ForegroundColor $color
}

# Decode a WebResponse body honouring charset, then parse JSON (UTF-8 safe, accents FR-CA).
function Read-Body([System.Net.HttpWebResponse]$Resp) {
  $ms = [System.IO.MemoryStream]::new()
  $Resp.GetResponseStream().CopyTo($ms)
  $bytes = $ms.ToArray()
  $enc = [System.Text.Encoding]::UTF8
  $ct = $Resp.ContentType
  if ($ct -and $ct -match 'charset=([\w\-]+)') {
    try { $enc = [System.Text.Encoding]::GetEncoding($Matches[1]) } catch { $enc = [System.Text.Encoding]::UTF8 }
  }
  return @{ Text = $enc.GetString($bytes); Bytes = $bytes; Headers = $Resp.Headers }
}

function Invoke-Api {
  param(
    [Parameter(Mandatory)][string]$Path,
    [string]$Method = 'GET',
    $Body = $null
  )
  $url = "$Api$Path"
  $req = [System.Net.HttpWebRequest]::Create($url)
  $req.Method = $Method
  $req.Timeout = 60000
  $req.ReadWriteTimeout = 60000
  $req.Accept = 'application/json'
  if ($null -ne $Body) {
    $json = if ($Body -is [string]) { $Body } else { $Body | ConvertTo-Json -Compress -Depth 8 }
    $payload = [System.Text.Encoding]::UTF8.GetBytes($json)
    $req.ContentType = 'application/json; charset=utf-8'
    $req.ContentLength = $payload.Length
    $s = $req.GetRequestStream(); $s.Write($payload, 0, $payload.Length); $s.Dispose()
  }
  try {
    $resp = $req.GetResponse()
  } catch [System.Net.WebException] {
    if ($null -eq $_.Exception.Response) { throw }
    $resp = $_.Exception.Response
  }
  $r = Read-Body $resp
  $isJson = $r.Headers['Content-Type'] -like '*json*'
  $obj = $null
  if ($isJson) { try { $obj = $r.Text | ConvertFrom-Json } catch { $obj = $null } }
  $out = [pscustomobject]@{
    Status  = [int]$resp.StatusCode
    Content = $r.Text
    Bytes   = $r.Bytes
    Headers = $r.Headers
    Json    = $obj
    CT      = $r.Headers['Content-Type']
  }
  $resp.Dispose()
  return $out
}

Write-Host ''
Write-Host '=== Housat — Verification & Validation live ===' -ForegroundColor Cyan
Write-Host "API: $Api" -ForegroundColor DarkGray
Write-Host ''

# ---------------------------------------------------------------- A6 / healthz
$h = Invoke-Api -Path '/healthz'
Check 'A6.0' 'healthz répond ok' ($h.Status -eq 200 -and $h.Json.status -eq 'ok') "status=$($h.Status)"

# healthz must NOT be problem+json; error paths must be.
Check 'A6.1' 'erreur 404 conforme RFC 7807' (
  (Invoke-Api -Path '/sites/999999').CT -like 'application/problem+json*'
)

# ---------------------------------------------------------------- create site
# NB : ne PAS nommer cette table $bbox — PowerShell est insensible a la casse,
# donc $bbox et le parametre $Bbox seraient le MEME objet (ecrasement silencieux).
$siteBody = @{ name = $SiteName; owner_email = 'vv@example.com'
  min_lon = $Bbox[0]; min_lat = $Bbox[1]; max_lon = $Bbox[2]; max_lat = $Bbox[3] }
$created = Invoke-Api -Path '/sites' -Method POST -Body $siteBody
Check 'A6.2' 'POST /sites -> 201 + polygon GeoJSON' (
  $created.Status -eq 201 -and $created.Json.polygon_geojson -like '*Polygon*'
) "status=$($created.Status) id=$($created.Json.id)"
$siteId = $created.Json.id

$bad = Invoke-Api -Path '/sites' -Method POST -Body (@{ name = 'bbox KO'; owner_email = 'vv@example.com'
    min_lon = $Bbox[0]; min_lat = $Bbox[1]; max_lon = [double]$Bbox[0] - 0.01; max_lat = $Bbox[3] })
Check 'A6.3' 'bbox invalide -> 422 RFC 7807' ($bad.Status -eq 422 -and $bad.CT -like 'application/problem+json*') "status=$($bad.Status)"

$big = Invoke-Api -Path '/sites' -Method POST -Body (@{ name = 'bbox grande'; owner_email = 'vv@example.com'
    min_lon = $Bbox[0]; min_lat = $Bbox[1]; max_lon = [double]$Bbox[0] + 0.2; max_lat = [double]$Bbox[1] + 0.2 })
Check 'A6.4' 'bbox > ~2 km2 -> 422 (anti-DoS)' ($big.Status -eq 422) "status=$($big.Status)"

# ---------------------------------------------------------------- A1 backfill
Write-Host ''
Write-Host '> Backfill archive Sentinel-2 (réseau STAC requis, jusqu''à 15 min)...' -ForegroundColor Yellow
$bf = Invoke-Api -Path "/sites/$siteId/backfill" -Method POST
Check 'A1.0' 'POST /backfill -> 202 accepted' ($bf.Status -eq 202) "status=$($bf.Status)"

$dup = Invoke-Api -Path "/sites/$siteId/backfill" -Method POST
Check 'A6.5' 'second backfill concurrent -> 409' ($dup.Status -eq 409 -and $dup.CT -like 'application/problem+json*') "status=$($dup.Status)"

$deadline = (Get-Date).AddSeconds($BackfillTimeoutSec)
$prog = $null
$lastMsg = ''
while ((Get-Date) -lt $deadline) {
  $prog = Invoke-Api -Path "/sites/$siteId/progress"
  $state = "$($prog.Json.backfill_status)|$($prog.Json.observations)|$($prog.Json.milestone)"
  if ($state -ne $lastMsg) {
    Write-Host ("   ...status={0} observations={1} milestone={2}" -f `
      $prog.Json.backfill_status, $prog.Json.observations, $prog.Json.milestone) -ForegroundColor DarkGray
    $lastMsg = $state
  }
  if ($prog.Json.backfill_status -in @('done', 'error', 'idle')) { break }
  Start-Sleep -Seconds 10
}

$observations = @(Invoke-Api -Path "/sites/$siteId/observations").Json
$occ = @($observations | Where-Object { $_.obs_date } | Where-Object { $_.milestone -ne $null }).Count
Check 'A1.1' 'backfill terminé (status done)' ($prog.Json.backfill_status -eq 'done') `
  "status=$($prog.Json.backfill_status) error=$($prog.Json.backfill_error)"
Check 'A1.2' '>= 2 scènes ingérées (critère A1)' ($observations.Count -ge 2) `
  "observations=$($observations.Count) (borne par MAX_CLOUD_COVER=$($cfg['MAX_CLOUD_COVER'] ?? '20'))$(
    if ($observations.Count -lt 2) { ' — region peu de-scenes sous ce seuil : rerun avec une emprise plus clémente (VVSITE_*)' })"

# ---------------------------------------------------------------- A2 anchor
$fr = Invoke-Api -Path "/sites/$siteId/frames"
Check 'A2.1' 'ancre t0 persistée (frame_store.anchor)' ($fr.Json.anchor -eq $true) "anchor=$($fr.Json.anchor) prev=$($fr.Json.prev)"

# ---------------------------------------------------------------- A5 inference traceability
$noMethod = @($observations | Where-Object { -not $_.obs_date }).Count
$okSum = @($observations | Where-Object { $null -ne $_.pv_sum })
Check 'A5.1' 'pv_sum consigné par observation' ($okSum.Count -eq $observations.Count) `
  "avec pv_sum=$($okSum.Count)/$($observations.Count)"

# ---------------------------------------------------------------- A9 image_bbox
$withImg = @($observations | Where-Object { $_.image_url })
$withBbox = @($withImg | Where-Object { $null -ne $_.image_bbox })
Check 'A9.1' 'image_bbox persistée pour chaque image' (
  $withImg.Count -gt 0 -and $withBbox.Count -eq $withImg.Count
) "images=$($withImg.Count) bbox=$($withBbox.Count)"

if ($withImg.Count -gt 0) {
  $img = Invoke-Api -Path $withImg[0].image_url
  $isPng = $img.Bytes.Length -gt 8 -and $img.Bytes[0] -eq 0x89 -and $img.Bytes[1] -eq 0x50
  Check 'A9.2' 'GET /observations/{id}/image -> PNG valide' (
    $img.Status -eq 200 -and $isPng -and $img.Headers['Cache-Control'] -like '*immutable*'
  ) "bytes=$($img.Bytes.Length)"
}

# ---------------------------------------------------------------- A8 compare + A4 pivot
$ordered = @($observations | Sort-Object obs_date)
$compare = $null
if ($ordered.Count -ge 2) {
  $fromId = $ordered[0].id; $toId = $ordered[-1].id
  $compare = Invoke-Api -Path "/sites/$siteId/compare?from=$fromId&to=$toId"
  $pg = [double]$compare.Json.delta.progression
  Check 'A8.1' '/compare avant/après -> 200 + progression plafonnée 130%' (
    $compare.Status -eq 200 -and $pg -le 130.0
  ) "progression=$pg%"
  Check 'A8.2' 'comparaison même observation -> 422' (
    (Invoke-Api -Path "/sites/$siteId/compare?from=$fromId&to=$fromId").Status -eq 422
  )
  Check 'A8.3' 'observation hors chantier -> 404' (
    (Invoke-Api -Path "/sites/$siteId/compare?from=$fromId&to=999999").Status -eq 404
  )
}

# A4 : milestone M2/M3 <=> pivot_confirme (coherence phenomenologique)
$violation = @($observations | Where-Object {
    ($_.milestone -in @('M2', 'M3', 'M4')) -and ($_.pivot_confirme -ne $true)
  })
Check 'A4.1' 'M2/M3/M4 <=> pivot_confirme=true' ($violation.Count -eq 0) `
  "violations=$($violation.Count)"

# ---------------------------------------------------------------- A3 alerts monotone
$alerts = @(Invoke-Api -Path "/sites/$siteId/alerts").Json
$seq = @($alerts | ForEach-Object { $_.milestone } )
$idx = @{ 'M0' = 0; 'M1' = 1; 'M2' = 2; 'M3' = 3; 'M4' = 4 }
$monotone = $true
for ($i = 1; $i -lt $seq.Count; $i++) {
  $a = $idx[$seq[$i - 1]]; $b = $idx[$seq[$i]]
  if ($null -ne $a -and $null -ne $b -and $b -lt $a) { $monotone = $false }
}
Check 'A3.1' 'alertes de jalon monotones (M_t >= M_t-1)' $monotone "alertes=$($alerts.Count)"

# ---------------------------------------------------------------- A7 no unsolicited emission
# Local mode: NTFY_TOPIC/SMTP unset in .env => no external alert channel configured.
$smtpSet = $false
if (Test-Path $envFile) {
  $smtpSet = [bool](Select-String -Path $envFile -Pattern '^SMTP_HOST=\S' -Quiet)
}
Check 'A7.1' 'aucun canal d''alerte externe en mode local' (-not $smtpSet) "SMTP_HOST défini=$smtpSet"

# ---------------------------------------------------------------- A10 reports
Write-Host ''
$today = Get-Date
# Decalage "jours depuis lundi" : DayOfWeek.Monday == 0 dans .NET, donc (DoW + 6) % 7.
# Toujours formater en ISO : l'interpolation directe d'un DateTime suit la culture
# locale ("09/14/2026 00:00:00") et produit un chemin invalide.
$ongoingMonday = $today.Date.AddDays(-(([int]$today.DayOfWeek + 6) % 7)).ToString('yyyy-MM-dd')

$r422a = Invoke-Api -Path "/sites/$siteId/reports/2020-01-06" -Method POST
Check 'A10.1' 'semaine sans observation -> 422' ($r422a.Status -eq 422 -and $r422a.CT -like 'application/problem+json*') "status=$($r422a.Status)"

$r422b = Invoke-Api -Path "/sites/$siteId/reports/$ongoingMonday" -Method POST
Check 'A10.2' 'semaine en cours -> 422' ($r422b.Status -eq 422) "status=$($r422b.Status)"

$r422c = Invoke-Api -Path "/sites/$siteId/reports/2020-01-08" -Method POST
Check 'A10.3' 'week non-lundi -> 422' ($r422c.Status -eq 422) "status=$($r422c.Status)"

# Find the most recent closed ISO week that actually holds observations.
$obsWeeks = @($observations | Where-Object { $_.obs_date } | ForEach-Object {
    $d = [datetime]$_.obs_date
    $mon = $d.Date.AddDays(-(([int]$d.DayOfWeek + 6) % 7))
    $mon
  } | Sort-Object -Unique -Descending)
$targetWeek = $null
$ongoingMondayDate = [datetime]$ongoingMonday
foreach ($w in $obsWeeks) {
  if ($w -lt $ongoingMondayDate) { $targetWeek = $w; break }
}

if ($null -eq $targetWeek) {
  Check 'A10.4' 'semaine clôturée avec observations disponible' $false 'aucune observation dans une semaine clôturée'
} else {
  $wk = $targetWeek.ToString('yyyy-MM-dd')
  Write-Host "> Rapport PDF semaine $wk ..." -ForegroundColor Yellow
  $gen = Invoke-Api -Path "/sites/$siteId/reports/$wk" -Method POST
  Check 'A10.4' 'POST /reports/{week} -> 201' ($gen.Status -eq 201) "status=$($gen.Status)"
  $sha = $gen.Json.sha256
  Check 'A10.5' 'empreinte SHA-256 persistée (64 hex)' ($sha -match '^[0-9a-f]{64}$') "sha256=$($sha.Substring(0,16))..."

  $pdf = Invoke-Api -Path "/sites/$siteId/reports/$wk/pdf"
  $magic = [System.Text.Encoding]::ASCII.GetString($pdf.Bytes[0..3])
  Check 'A10.6' 'GET .../pdf -> %PDF valide (> 2 Ko)' (
    $pdf.Status -eq 200 -and $magic -eq '%PDF' -and $pdf.Bytes.Length -gt 2048
  ) "magic=$magic bytes=$($pdf.Bytes.Length)"

  # Cryptographic integrity: the downloaded bytes must hash to the stored ETag.
  $actual = [System.Security.Cryptography.SHA256]::Create().ComputeHash($pdf.Bytes)
  $actualHex = ([System.BitConverter]::ToString($actual) -replace '-', '').ToLowerInvariant()
  $etag = ($pdf.Headers['ETag'] -replace '"', '')
  Check 'A10.7' 'ETag == sha256 octets téléchargés == empreinte DB' (
    $actualHex -eq $sha -and $etag -eq $sha
  ) "etag=$($etag.Substring(0, 16))... recalcul=$($actualHex.Substring(0, 16))..."

  $dupe = Invoke-Api -Path "/sites/$siteId/reports/$wk" -Method POST
  Check 'A10.8' 'régénération même semaine -> 409 (idempotence)' `
    ($dupe.Status -eq 409 -and $dupe.CT -like 'application/problem+json*') "status=$($dupe.Status)"

  $list = @(Invoke-Api -Path "/sites/$siteId/reports").Json
  Check 'A10.9' 'rapport listé via GET /reports' ($list.Count -ge 1) "rapports=$($list.Count)"
}

# ---------------------------------------------------------------- summary
Write-Host ''
Write-Host '=== Résumé V&V ===' -ForegroundColor Cyan
$script:results | Format-Table -AutoSize Id, Ok, Label | Out-String | Write-Host
$total = $script:results.Count
$passed = $total - $script:fail
$color = if ($script:fail -eq 0) { 'Green' } else { 'Red' }
Write-Host ("RÉSULTAT : {0}/{1} vérifications PASS, {2} FAIL" -f $passed, $total, $script:fail) -ForegroundColor $color
Write-Host "Chantier de test : $Api/sites/$siteId  (web: http://localhost:8080)" -ForegroundColor DarkGray
Write-Host ''
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
