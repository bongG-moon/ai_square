# One-shot, same-user handoff. Never installs a package or rewrites app state.
param([string]$Package, [string]$HostExe, [string]$StateRoot)
$ErrorActionPreference = 'Stop'

function Stop-WorkspaceResolution([int]$Code) { throw ('AX_RESOLVE:' + $Code) }

function Assert-WorkspacePath([string]$Path, [int]$Code = 71) {
    if ([string]::IsNullOrWhiteSpace($Path) -or $Path -match '["\x00-\x1f]' -or
        $Path -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\/]+[\\/][^\\/]+)') { Stop-WorkspaceResolution $Code }
    try {
        $full = [IO.Path]::GetFullPath($Path)
        $cursor = $full
        while ($cursor) {
            if (Test-Path -LiteralPath $cursor) {
                if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { Stop-WorkspaceResolution $Code }
            }
            $cursor = [IO.Path]::GetDirectoryName($cursor)
        }
        return $full
    } catch { Stop-WorkspaceResolution $Code }
}

function Read-WorkspaceBytes([string]$Path, [long]$Limit, [int]$Code = 71) {
    $null = Assert-WorkspacePath $Path $Code
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        try {
            if ($stream.Length -lt 1 -or $stream.Length -gt $Limit) { Stop-WorkspaceResolution $Code }
            $bytes = New-Object byte[] ([int]$stream.Length)
            $offset = 0
            while ($offset -lt $bytes.Length) {
                $count = $stream.Read($bytes, $offset, $bytes.Length - $offset)
                if ($count -le 0) { Stop-WorkspaceResolution $Code }
                $offset += $count
            }
            if ($stream.ReadByte() -ne -1) { Stop-WorkspaceResolution $Code }
            return ,$bytes
        } finally { $stream.Dispose() }
    } catch { Stop-WorkspaceResolution $Code }
}

function Get-WorkspaceHash([string]$Path, [long]$Limit = 209715200) {
    $null = Assert-WorkspacePath $Path
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $length = $stream.Length
            if ($length -lt 0 -or $length -gt $Limit) { Stop-WorkspaceResolution 71 }
            $hash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '').ToLowerInvariant()
            if ($stream.Length -ne $length) { Stop-WorkspaceResolution 71 }
            return $hash
        } finally { $stream.Dispose(); $sha.Dispose() }
    } catch { Stop-WorkspaceResolution 71 }
}

function Assert-WorkspaceJsonKeys([string]$Text) {
    # ConvertFrom-Json otherwise silently accepts duplicate property names.
    # Scan only JSON structure; quoted property names are decoded as a string.
    $objects = New-Object Collections.ArrayList
    for ($i = 0; $i -lt $Text.Length; $i++) {
        $character = $Text[$i]
        if ($character -eq '{') {
            $null = $objects.Add((New-Object 'Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)))
            if ($objects.Count -gt 4) { Stop-WorkspaceResolution 71 }
        } elseif ($character -eq '}') {
            if ($objects.Count -eq 0) { Stop-WorkspaceResolution 71 }
            $objects.RemoveAt($objects.Count - 1)
        } elseif ($character -eq '"') {
            $start = $i
            do {
                $i++
                if ($i -ge $Text.Length) { Stop-WorkspaceResolution 71 }
                if ($Text[$i] -eq '\') { $i++; continue }
                if ($Text[$i] -eq '"') { break }
            } while ($true)
            $end = $i + 1
            while ($end -lt $Text.Length -and [char]::IsWhiteSpace($Text[$end])) { $end++ }
            if ($end -lt $Text.Length -and $Text[$end] -eq ':') {
                if ($objects.Count -eq 0) { Stop-WorkspaceResolution 71 }
                try { $key = (ConvertFrom-Json ('{"value":' + $Text.Substring($start, $i - $start + 1) + '}')).value }
                catch { Stop-WorkspaceResolution 71 }
                if (-not $objects[$objects.Count - 1].Add([string]$key)) { Stop-WorkspaceResolution 71 }
            }
        }
    }
    if ($objects.Count -ne 0) { Stop-WorkspaceResolution 71 }
}

function ConvertTo-WorkspaceVersion([string]$Value) {
    if ($Value -cnotmatch '^(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})$') { Stop-WorkspaceResolution 71 }
    try { return [version]$Value } catch { Stop-WorkspaceResolution 71 }
}

function Get-WorkspaceManagedCandidate([string]$State) {
    $updates = Join-Path $State 'updates'
    $pointer = Join-Path $updates 'current.json'
    $null = Assert-WorkspacePath $pointer
    if (-not (Test-Path -LiteralPath $pointer)) { return $null }
    $raw = Read-WorkspaceBytes $pointer 262144
    try {
        $text = (New-Object Text.UTF8Encoding($false, $true)).GetString($raw).TrimStart([char]0xfeff)
        Assert-WorkspaceJsonKeys $text
        $current = ConvertFrom-Json $text
        if ($current -isnot [pscustomobject] -or
            (@($current.PSObject.Properties.Name | Sort-Object) -join ',') -cne 'files,root,schema,sha256,version' -or
            ($current.schema -isnot [int] -and $current.schema -isnot [long]) -or $current.schema -ne 1 -or
            $current.version -isnot [string] -or $current.sha256 -isnot [string] -or
            $current.sha256 -cnotmatch '^[a-f0-9]{64}$' -or
            $current.root -cne ('versions/' + $current.version + '/Company-Workspace')) { Stop-WorkspaceResolution 71 }
        $version = ConvertTo-WorkspaceVersion $current.version
        $properties = @($current.files.PSObject.Properties)
        if ($current.files -isnot [pscustomobject] -or $properties.Count -lt 2 -or $properties.Count -gt 500) { Stop-WorkspaceResolution 71 }
        $application = Assert-WorkspacePath (Join-Path $updates $current.root)
        $expected = @{}
        $total = 0L
        foreach ($file in $properties) {
            $relative = $file.Name
            if ($relative.Length -gt 240 -or $relative -match '[\\<>:"|?*\x00-\x1f]' -or
                $file.Value -isnot [string] -or $file.Value -cnotmatch '^[a-f0-9]{64}$') { Stop-WorkspaceResolution 71 }
            foreach ($part in $relative.Split('/')) {
                if (-not $part -or $part -in @('.', '..', 'runtime', 'updates', '.git', '.env', '__pycache__', 'runtime.json', 'upgrade-drafts.json', 'upgrade-launch.lock') -or
                    $part.EndsWith('.') -or $part.EndsWith(' ') -or $part -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') { Stop-WorkspaceResolution 71 }
            }
            if ($expected.ContainsKey($relative)) { Stop-WorkspaceResolution 71 }
            $expected[$relative] = $true
            $filePath = Assert-WorkspacePath (Join-Path $application $relative)
            if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) { Stop-WorkspaceResolution 71 }
            $total += (Get-Item -LiteralPath $filePath).Length
            if ($total -gt 209715200 -or (Get-WorkspaceHash $filePath) -cne $file.Value) { Stop-WorkspaceResolution 71 }
        }
        if (-not $expected.ContainsKey('deploy/Start-CompanyWorkspace.ps1') -or -not $expected.ContainsKey('local_app/server.py')) { Stop-WorkspaceResolution 71 }
        $queue = New-Object 'Collections.Generic.Queue[string]'
        $queue.Enqueue($application)
        $visited = 0
        while ($queue.Count) {
            foreach ($entry in Get-ChildItem -LiteralPath $queue.Dequeue() -Force) {
                if (++$visited -gt 1000 -or ($entry.Attributes -band [IO.FileAttributes]::ReparsePoint)) { Stop-WorkspaceResolution 71 }
                if ($entry.PSIsContainer) { $queue.Enqueue($entry.FullName); continue }
                $name = $entry.FullName.Substring($application.Length + 1).Replace('\', '/')
                if (-not $expected.ContainsKey($name)) { Stop-WorkspaceResolution 71 }
            }
        }
        $again = Read-WorkspaceBytes $pointer 262144
        if ([Convert]::ToBase64String($raw) -cne [Convert]::ToBase64String($again)) { Stop-WorkspaceResolution 71 }
        # Earlier same-number 0.23.32 builds did not have this import contract.
        if ($version -lt [version]'0.23.32' -or -not $expected.ContainsKey('local_app/extension_open_client.py')) { return $null }
        $launcher = Join-Path $application 'deploy/Start-CompanyWorkspace.ps1'
        $launcherText = [IO.File]::ReadAllText($launcher)
        if ($launcherText -notmatch '\[string\]\s*\$ExtensionPackage\b') { return $null }
        return [pscustomobject]@{kind='managed'; version=$version; executable=$launcher; directory=$application; pointer=$pointer; pointerHash=(Get-WorkspaceHash $pointer 262144)}
    } catch { Stop-WorkspaceResolution 71 }
}

function Get-WorkspaceInstalledCandidate([string]$Executable) {
    if ([string]::IsNullOrWhiteSpace($Executable)) { return $null }
    $path = Assert-WorkspacePath $Executable 72
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
    $directory = [IO.Path]::GetDirectoryName($path)
    $marker = Join-Path $directory 'AX-Workspace.install-id'
    if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { return $null }
    $markerBytes = Read-WorkspaceBytes $marker 128 72
    $id = (New-Object Text.UTF8Encoding($false, $true)).GetString($markerBytes)
    if ($id -cnotin @('AX.Workspace.Desktop', "AX.Workspace.Desktop`r`n", "AX.Workspace.Desktop`n")) { return $null }
    $metadata = [Diagnostics.FileVersionInfo]::GetVersionInfo($path)
    $version = [version]'0.0.0'
    if ($metadata.FileMajorPart -ge 0 -and $metadata.FileMinorPart -ge 0 -and $metadata.FileBuildPart -ge 0) {
        $version = [version]('{0}.{1}.{2}' -f $metadata.FileMajorPart, $metadata.FileMinorPart, $metadata.FileBuildPart)
    }
    return [pscustomobject]@{kind='installed'; version=$version; executable=$path; directory=$directory}
}

function Test-WorkspaceImportCapability([string]$Path) {
    # Read-only capability hint: never launch a legacy host just to probe it.
    # Scan bounded chunks, and only when the installed EXE is actually selected.
    # Main/constructors/resources are not loaded or executed for this check.
    $null = Assert-WorkspacePath $Path 72
    try {
        $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        try {
            if ($stream.Length -lt 2 -or $stream.Length -gt 83886080 -or $stream.ReadByte() -ne 77 -or $stream.ReadByte() -ne 90) { return $false }
            $buffer = New-Object byte[] 65536
            $tail = New-Object byte[] 0
            while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) {
                $block = New-Object byte[] ($tail.Length + $read)
                [Array]::Copy($tail, 0, $block, 0, $tail.Length)
                [Array]::Copy($buffer, 0, $block, $tail.Length, $read)
                if ([Text.Encoding]::Unicode.GetString($block).Contains('--import-extension') -or
                    [Text.Encoding]::Unicode.GetString($block, 1, $block.Length - 1).Contains('--import-extension')) { return $true }
                $count = [Math]::Min(64, $block.Length)
                $tail = New-Object byte[] $count
                [Array]::Copy($block, $block.Length - $count, $tail, 0, $count)
            }
            return $false
        } finally { $stream.Dispose() }
    } catch { Stop-WorkspaceResolution 72 }
}

function Resolve-WorkspaceTarget([string]$State, [string]$InstalledExe) {
    $statePath = Assert-WorkspacePath $State 70
    $managed = Get-WorkspaceManagedCandidate $statePath
    try { $installed = Get-WorkspaceInstalledCandidate $InstalledExe }
    catch { if ($managed) { return $managed }; throw }
    # Prefer the activated runtime for equal versions: same-number fixes exist.
    if ($managed -and (-not $installed -or $managed.version -ge $installed.version)) { return $managed }
    if ($installed -and (Test-WorkspaceImportCapability $installed.executable)) { return $installed }
    if ($managed -and $installed -and $managed.version -lt $installed.version) { Stop-WorkspaceResolution 73 }
    if ($installed) { Stop-WorkspaceResolution 73 }
    Stop-WorkspaceResolution 72
}

function Quote-WorkspaceArgument([string]$Value) {
    if ($Value -match '["\x00-\x1f]') { Stop-WorkspaceResolution 70 }
    return '"' + $Value + [regex]::Match($Value, '\\+$').Value + '"'
}

function Invoke-WorkspaceResolvedHandoff([object]$Target, [string]$State, [string]$File) {
    $start = New-Object Diagnostics.ProcessStartInfo
    if ($Target.kind -eq 'managed') {
        if ((Get-WorkspaceHash $Target.pointer 262144) -cne $Target.pointerHash) { Stop-WorkspaceResolution 71 }
        $powershell = Join-Path ([Environment]::GetFolderPath('System')) 'WindowsPowerShell\v1.0\powershell.exe'
        if (-not (Test-Path -LiteralPath $powershell -PathType Leaf)) { Stop-WorkspaceResolution 74 }
        $start.FileName = $powershell
        # Keep the common launcher's normal profile/environment inheritance.
        $start.Arguments = '-NoLogo -ExecutionPolicy Bypass -WindowStyle Hidden -File ' + (Quote-WorkspaceArgument $Target.executable) +
            ' -StateRoot ' + (Quote-WorkspaceArgument $State) + ' -ExtensionPackage ' + (Quote-WorkspaceArgument $File)
    } else {
        $start.FileName = $Target.executable
        $start.Arguments = '--import-extension ' + (Quote-WorkspaceArgument $File) + ' --state ' + (Quote-WorkspaceArgument $State)
    }
    $start.WorkingDirectory = $Target.directory
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
    $start.EnvironmentVariables['PYTHONDONTWRITEBYTECODE'] = '1'
    $process = $null
    try {
        try { $process = [Diagnostics.Process]::Start($start) } catch { Stop-WorkspaceResolution 74 }
        if (-not $process) { Stop-WorkspaceResolution 74 }
        # No second target/retry after start: a lost acknowledgement may mean
        # the application has already accepted the package and displayed review.
        if (-not $process.WaitForExit(180000)) {
            # Retire only our startup process, never the app or its work tree.
            try { $process.Kill(); $null = $process.WaitForExit(2000) } catch {}
            Stop-WorkspaceResolution 75
        }
        return $process.ExitCode
    } finally { if ($process) { $process.Dispose() } }
}

function Invoke-WorkspaceImport([string]$File, [string]$InstalledExe, [string]$State) {
    $packagePath = Assert-WorkspacePath $File 70
    if ([IO.Path]::GetExtension($packagePath) -notin @('.axextension', '.zip') -or
        -not (Test-Path -LiteralPath $packagePath -PathType Leaf)) { Stop-WorkspaceResolution 70 }
    $size = (Get-Item -LiteralPath $packagePath).Length
    if ($size -lt 1 -or $size -gt 16777216) { Stop-WorkspaceResolution 70 }
    if (-not $State) { $State = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'CompanyAgent\local-ui' }
    $State = Assert-WorkspacePath $State 70
    $target = Resolve-WorkspaceTarget $State $InstalledExe
    return Invoke-WorkspaceResolvedHandoff $target $State $packagePath
}

if ($MyInvocation.InvocationName -ne '.') {
    try { exit (Invoke-WorkspaceImport $Package $HostExe $StateRoot) }
    catch {
        if ($_.Exception.Message -match '^AX_RESOLVE:(70|71|72|73|74|75)$') { exit ([int]$Matches[1]) }
        exit 74
    }
}
