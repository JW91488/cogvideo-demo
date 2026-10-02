@echo off
cd /d %~dp0
uv run python generate_video.py %*
echo.
echo ================================================
echo  Video saved in the "outputs" folder.
echo  You can close this window now.
pause
