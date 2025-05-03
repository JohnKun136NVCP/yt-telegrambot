$downloadUrl = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip"
$destinationPath = "$env:TEMP\ffmpeg.zip"
$extractFolder = "$env:TEMP\FFmpeg"
$finalPath = "C:\FFmpeg"

# Download FFmpeg
Write-Host "Downloading FFmpeg..."
Invoke-WebRequest -Uri $downloadUrl -OutFile $destinationPath

# Extract FFmpeg
Write-Host "Extracting FFmpeg..."
Expand-Archive -Path $destinationPath -DestinationPath $extractFolder -Force

# Move FFmpeg to C:\FFmpeg
Write-Host "Moving FFmpeg to $finalPath..."
Move-Item -Path "$extractFolder\ffmpeg-master-latest-win64-gpl-shared" -Destination $finalPath -Force

# Add FFmpeg to environment variables
$envPath = [System.Environment]::GetEnvironmentVariable("Path", [System.EnvironmentVariableTarget]::Machine)
$newPath = "$finalPath\bin;$envPath"
[System.Environment]::SetEnvironmentVariable("Path", $newPath, [System.EnvironmentVariableTarget]::Machine)

Write-Host "FFmpeg installation complete! Try to open a new command prompt and type 'ffmpeg' to verify the installation."

