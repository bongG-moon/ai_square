# Local trial only. The MongoDB ZIP is downloaded separately from mongodb.com.
$ErrorActionPreference = 'Stop'
$mongoRoot = Join-Path (Split-Path -Parent $PSScriptRoot) '.local-mongo'
$mongoExe = Get-ChildItem (Join-Path $mongoRoot 'server') -Recurse -Filter mongod.exe | Select-Object -First 1
if (-not $mongoExe) { throw 'Extract the official MongoDB Windows ZIP into pt_ai_square/.local-mongo/server first.' }
if (Get-NetTCPConnection -LocalPort 27018 -State Listen -ErrorAction SilentlyContinue) {
    Write-Output 'Port 27018 is already listening. Reuse the existing local MongoDB if it belongs to this project.'
    exit 0
}
New-Item -ItemType Directory -Force (Join-Path $mongoRoot 'data') | Out-Null
$mongoArgs = @('--dbpath', ('"' + (Join-Path $mongoRoot 'data') + '"'), '--bind_ip', '127.0.0.1', '--port', '27018', '--logpath', ('"' + (Join-Path $mongoRoot 'mongod.log') + '"'), '--logappend')
$mongoProcess = Start-Process -FilePath $mongoExe.FullName -ArgumentList $mongoArgs -WindowStyle Hidden -PassThru
Write-Output "Local MongoDB started (PID $($mongoProcess.Id)). Log: $mongoRoot/mongod.log"
