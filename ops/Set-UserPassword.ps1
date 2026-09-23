<#
.SYNOPSIS
    Administrative tool to set/reset user passwords in the local student advisor database.
.PARAMETER Email
    Email of the user to update (e.g. student@demo.local).
.PARAMETER AllDemo
    Switch to reset all 4 demo accounts (student, student2, advisor, admin).
.PARAMETER Password
    New password (12-256 characters). If not provided, prompts securely via Read-Host.
#>
[CmdletBinding()]
param(
    [string]$Email = "",
    [switch]$AllDemo,
    [string]$Password = ""
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot

try {
    if (-not $AllDemo -and [string]::IsNullOrWhiteSpace($Email)) {
        throw "Vui lòng chỉ định -Email (ví dụ: student@demo.local) hoặc switch -AllDemo"
    }

    if ([string]::IsNullOrWhiteSpace($Password)) {
        $secPw = Read-Host -Prompt "Nhập mật khẩu mới (12-256 ký tự)" -AsSecureString
        $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secPw)
        $Password = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)

        $secConfirm = Read-Host -Prompt "Xác nhận lại mật khẩu" -AsSecureString
        $BSTR2 = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secConfirm)
        $confirm = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR2)
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR2)

        if ($Password -ne $confirm) {
            throw "Mật khẩu xác nhận không khớp!"
        }
    }

    if ($Password.Length -lt 12 -or $Password.Length -gt 256) {
        throw "Mật khẩu phải có độ dài từ 12 đến 256 ký tự theo quy định bảo mật."
    }

    $apiContainer = (docker compose ps -q api).Trim()
    if (-not $apiContainer) {
        throw "Container 'api' không hoạt động. Hãy chạy ops/Start-Local.ps1 trước."
    }

    if ($AllDemo) {
        Write-Host "Đang cập nhật mật khẩu cho toàn bộ tài khoản DEMO..."
        docker compose exec -T api python -m app.reset_password --all-demo --password "$Password"
    } else {
        Write-Host "Đang cập nhật mật khẩu cho tài khoản $Email..."
        docker compose exec -T api python -m app.reset_password --email "$Email" --password "$Password"
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Đổi mật khẩu thất bại với exit code $LASTEXITCODE"
    }
    Write-Host "SUCCESS: Cập nhật mật khẩu hoàn tất! Bạn có thể đăng nhập ngay bây giờ."
} finally {
    Pop-Location
}
