[CmdletBinding()]
param(
    [Parameter(Mandatory)][uri]$Site,
    [Parameter(Mandatory)][string]$Runtime,
    [string]$Wheels,
    [string]$Journal,
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Crie a .venv na pasta do projeto e instale requirements.txt.'
}
if (-not $Site.IsAbsoluteUri -or $Site.Scheme -ne 'https' -or $Site.AbsolutePath -ne '/' -or
    $Site.UserInfo -or $Site.Query -or $Site.Fragment) {
    throw 'Informe apenas a origem HTTPS do site.'
}

$Runtime = (Resolve-Path -LiteralPath $Runtime).Path
if (-not $Wheels) { $Wheels = Join-Path $Runtime 'wheels' }
$Wheels = (Resolve-Path -LiteralPath $Wheels).Path
if (-not $Journal) { $Journal = Join-Path $Runtime 'worker.db' }
if ($Journal -notmatch '^(?:[A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+\\)') {
    throw 'Informe um caminho absoluto para o journal.'
}
$Journal = [IO.Path]::GetFullPath($Journal)
if (-not (Test-Path -LiteralPath (Split-Path -Parent $Journal) -PathType Container)) {
    throw 'Crie a pasta privada do journal antes de iniciar.'
}
foreach ($privatePath in @($Runtime, $Wheels, $Journal)) {
    if ($privatePath -ieq $root -or $privatePath.StartsWith("$root\", [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Guarde o runtime, os wheels e o journal fora do repositório.'
    }
}

$envNames = @('LAB_WORKER_SITE', 'LAB_QEMU_RUNTIME', 'LAB_QEMU_WHEELS',
              'LAB_WORKER_JOURNAL', 'LAB_WORKER_TOKEN')
$previous = @{}
foreach ($name in $envNames) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
$secret = $null
Push-Location -LiteralPath $root
try {
    & $python -c 'from scripts.qemu_incident import QemuIncident; from pathlib import Path; import shutil, sys; vm=QemuIncident(sys.argv[1], sys.argv[2]); sys.exit(int(shutil.disk_usage(vm.runtime).free < 1200 * 1024**2))' $Runtime $Wheels
    if ($LASTEXITCODE -ne 0) { throw 'Confira QEMU, imagem, pycdlib, wheels e espaço disponível.' }
    $imageTool = Join-Path $Runtime 'qemu\qemu-img.exe'
    $info = & $imageTool info --output=json (Join-Path $Runtime 'ubuntu-base.img')
    if ($LASTEXITCODE -ne 0) { throw 'O QEMU não conseguiu ler a imagem-base.' }
    $image = $info | ConvertFrom-Json
    if ($image.format -ne 'qcow2' -or $image.'backing-filename') {
        throw 'Use uma imagem-base Ubuntu qcow2 independente, sem disco pai.'
    }
    Write-Host 'Runtime QEMU, imagem e dependências locais encontrados.'
    if ($CheckOnly) { return }

    $env:LAB_WORKER_SITE = $Site.GetLeftPart([UriPartial]::Authority)
    $env:LAB_QEMU_RUNTIME = $Runtime
    $env:LAB_QEMU_WHEELS = $Wheels
    $env:LAB_WORKER_JOURNAL = $Journal
    $secret = Read-Host 'Cole o token privado do executor' -AsSecureString
    $credential = [PSCredential]::new('worker', $secret)
    $env:LAB_WORKER_TOKEN = $credential.GetNetworkCredential().Password
    Write-Host 'Iniciando o executor. Mantenha esta janela aberta.'
    & $python (Join-Path $PSScriptRoot 'remote_worker.py')
    if ($LASTEXITCODE -ne 0) { throw "Executor encerrou com código $LASTEXITCODE." }
} finally {
    foreach ($name in $envNames) {
        if ($null -eq $previous[$name]) {
            Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
        } else {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
        }
    }
    if ($null -ne $secret) { $secret.Dispose() }
    Pop-Location
}
