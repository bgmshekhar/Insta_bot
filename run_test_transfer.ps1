$LocalPath = "D:\Tools\Insta_bot\test_yt.py"
$RemotePath = "/data/data/com.termux/files/home/storage/Insta_bot/test_yt.py"
$SSH_KEY  = "C:\Users\csy23\.ssh\id_termux_nopass"
$SSH_HOST = "u0_a157@192.168.1.12"
$SSH_PORT = "8022"

$bytes = [IO.File]::ReadAllBytes($LocalPath)
$b64   = [Convert]::ToBase64String($bytes)
$tmpFile = [System.IO.Path]::GetTempFileName() + ".b64"
$writer  = [IO.StreamWriter]::new($tmpFile, $false, [Text.Encoding]::ASCII)
$writer.Write($b64)
$writer.Close()

$remoteTmp = "/data/data/com.termux/files/home/_deploy_tmp.b64"
$sshArgs = "-i `"$SSH_KEY`" -p $SSH_PORT $SSH_HOST `"cat > $remoteTmp`""
cmd.exe /c "type `"$tmpFile`" | ssh $sshArgs"
ssh -i $SSH_KEY -p $SSH_PORT $SSH_HOST "base64 -d $remoteTmp > $RemotePath && rm $remoteTmp"
Remove-Item $tmpFile -ErrorAction SilentlyContinue
Write-Host "File transferred."
