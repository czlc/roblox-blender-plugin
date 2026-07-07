@echo off
setlocal

set "PACKAGE_ROOT=%~dp0"
set "PACKAGE_SCRIPT_NAME=%~nx0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; $root=[System.IO.Path]::GetFullPath($env:PACKAGE_ROOT); if(-not $root.EndsWith([System.IO.Path]::DirectorySeparatorChar)){ $root += [System.IO.Path]::DirectorySeparatorChar }; $stage=Join-Path $env:TEMP 'upload-to-roblox-package'; $addon=Join-Path $stage 'upload_to_roblox'; $zip=Join-Path $root 'upload-to-roblox.zip'; $excludedDirs=@('.git','.github','.vscode','.agents','__pycache__','dependencies_public'); $excludedFiles=@('upload-to-roblox.zip',$env:PACKAGE_SCRIPT_NAME); if(Test-Path -LiteralPath $stage){ Remove-Item -LiteralPath $stage -Recurse -Force }; New-Item -ItemType Directory -Path $addon -Force | Out-Null; foreach($item in Get-ChildItem -LiteralPath $root -Force -Recurse -File){ $relative=$item.FullName.Substring($root.Length).TrimStart('\','/'); $parts=$relative -split '[\\/]'; if($parts | Where-Object { $excludedDirs -contains $_ }){ continue }; if($excludedFiles -contains $item.Name -or $item.Extension -eq '.pyc' -or $item.Extension -eq '.zip'){ continue }; $target=Join-Path $addon $relative; New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null; Copy-Item -LiteralPath $item.FullName -Destination $target -Force }; if(Test-Path -LiteralPath $zip){ Remove-Item -LiteralPath $zip -Force }; Push-Location -LiteralPath $stage; try { Compress-Archive -LiteralPath 'upload_to_roblox' -DestinationPath $zip -Force } finally { Pop-Location }; Remove-Item -LiteralPath $stage -Recurse -Force; Write-Host ('Created ' + $zip)"

if errorlevel 1 (
    echo Failed to create upload-to-roblox.zip
    exit /b 1
)

echo Done.
