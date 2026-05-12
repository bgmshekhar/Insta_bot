#!/usr/bin/env pwsh
# deploy.ps1 — Transfer files to Termux via SSH (base64 encoding, no SFTP needed)

$SSH_KEY  = "C:\Users\csy23\.ssh\id_termux_nopass"
$SSH_HOST = "u0_a157@192.168.1.12"
$SSH_PORT = "8022"
$REMOTE   = "/data/data/com.termux/files/home/storage/Insta_bot"

function Transfer-File {
    param($LocalPath, $RemotePath)
    Write-Host "  -> Sending $((Split-Path $LocalPath -Leaf))..."
    $bytes = [IO.File]::ReadAllBytes($LocalPath)
    $b64   = [Convert]::ToBase64String($bytes)

    # Write clean ASCII b64 (no BOM, no CRLF) to a local temp file
    $tmpFile = [System.IO.Path]::GetTempFileName() + ".b64"
    $writer  = [IO.StreamWriter]::new($tmpFile, $false, [Text.Encoding]::ASCII)
    $writer.Write($b64)
    $writer.Close()

    $remoteTmp = "/data/data/com.termux/files/home/_deploy_tmp.b64"
    try {
        # Use cmd.exe /c type to pipe raw bytes (avoids PowerShell CRLF mangling)
        $sshArgs = "-i `"$SSH_KEY`" -p $SSH_PORT $SSH_HOST `"cat > $remoteTmp`""
        cmd.exe /c "type `"$tmpFile`" | ssh $sshArgs"
        if ($LASTEXITCODE -ne 0) { Write-Error "Stream failed for $LocalPath"; exit 1 }

        ssh -i $SSH_KEY -p $SSH_PORT $SSH_HOST "base64 -d $remoteTmp > $RemotePath && rm $remoteTmp"
        if ($LASTEXITCODE -ne 0) { Write-Error "Decode failed for $LocalPath"; exit 1 }
        Write-Host "     OK"
    } finally {
        Remove-Item $tmpFile -ErrorAction SilentlyContinue
    }
}

Write-Host "=== Deploying InstaBot to Termux ==="

# Core bot files
Transfer-File "d:\Tools\Insta_bot\telegram_bot\bot.py"           "$REMOTE/telegram_bot/bot.py"
Transfer-File "d:\Tools\Insta_bot\telegram_bot\database.py"      "$REMOTE/telegram_bot/database.py"
Transfer-File "d:\Tools\Insta_bot\telegram_bot\file_server.py"   "$REMOTE/telegram_bot/file_server.py"
Transfer-File "d:\Tools\Insta_bot\telegram_bot\requirements.txt" "$REMOTE/telegram_bot/requirements.txt"
Transfer-File "d:\Tools\Insta_bot\.env"                          "$REMOTE/.env"

# Plugin extractors
ssh -i $SSH_KEY -p $SSH_PORT $SSH_HOST "mkdir -p $REMOTE/telegram_bot/extractors"
Transfer-File "d:\Tools\Insta_bot\telegram_bot\extractors\__init__.py" "$REMOTE/telegram_bot/extractors/__init__.py"
Transfer-File "d:\Tools\Insta_bot\telegram_bot\extractors\base.py"     "$REMOTE/telegram_bot/extractors/base.py"
Transfer-File "d:\Tools\Insta_bot\telegram_bot\extractors\manager.py"  "$REMOTE/telegram_bot/extractors/manager.py"
Transfer-File "d:\Tools\Insta_bot\telegram_bot\extractors\youtube.py"  "$REMOTE/telegram_bot/extractors/youtube.py"
Transfer-File "d:\Tools\Insta_bot\telegram_bot\extractors\instagram.py" "$REMOTE/telegram_bot/extractors/instagram.py"

# Migration script
ssh -i $SSH_KEY -p $SSH_PORT $SSH_HOST "mkdir -p $REMOTE/telegram_bot/scripts"
Transfer-File "d:\Tools\Insta_bot\telegram_bot\scripts\migrate_users.py" "$REMOTE/telegram_bot/scripts/migrate_users.py"

Write-Host ""
Write-Host "=== Installing new dependencies on server ==="
ssh -i $SSH_KEY -p $SSH_PORT $SSH_HOST "cd $REMOTE && source venv/bin/activate && pip install -q -r telegram_bot/requirements.txt && echo 'pip OK'"

Write-Host ""
Write-Host "=== Running one-time DB migration (safe to run multiple times) ==="
ssh -i $SSH_KEY -p $SSH_PORT $SSH_HOST "cd $REMOTE/telegram_bot && source ../venv/bin/activate && python scripts/migrate_users.py && echo 'Migration OK'"

Write-Host ""
Write-Host "=== Restarting bot ==="
ssh -i $SSH_KEY -p $SSH_PORT $SSH_HOST "cd $REMOTE && sh manage-instabot.sh restart && echo 'Restart OK'"

Write-Host ""
Write-Host "=== Ensuring Cloudflare tunnel (instabot) is running ==="
# Kill any stale instabot tunnel, then start fresh in a tmux pane
ssh -i $SSH_KEY -p $SSH_PORT $SSH_HOST @'
tmux has-session -t instabot_tunnel 2>/dev/null && tmux kill-session -t instabot_tunnel
tmux new-session -d -s instabot_tunnel "cloudflared tunnel --config /data/data/com.termux/files/home/.cloudflared/config-instabot.yml run 2>&1 | tee -a /data/data/com.termux/files/home/storage/Insta_bot/logs/tunnel.log"
echo "Tunnel session started."
'@

Write-Host ""
Write-Host "=== Waiting 12s for services to start... ==="
Start-Sleep -Seconds 12

Write-Host "=== Testing health endpoint via Cloudflare tunnel ==="
try {
    $r = Invoke-WebRequest -Uri "https://bot.csydev.online/health" -TimeoutSec 15
    Write-Host "Health check PASS: $($r.StatusCode) - $($r.Content)"
} catch {
    Write-Warning "Health check via tunnel failed (may still be propagating): $_"
    Write-Host "  Trying local direct endpoint..."
    try {
        $r2 = Invoke-WebRequest -Uri "http://192.168.1.12:8500/health" -TimeoutSec 10
        Write-Host "  Local health check PASS: $($r2.StatusCode) - $($r2.Content)"
    } catch {
        Write-Warning "  Local health also failed: $_"
    }
}
