@echo off
rem email-tool setup for ChatGPT desktop and Codex on Windows: installs uv, which runs email-tool.
rem The same command as the Install page in the documentation, so nothing needs typing.
echo Installing uv, the program that runs email-tool. This takes about a minute.
echo.
powershell -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
if errorlevel 1 (
  echo.
  echo The installation did not finish. See https://skhan61.github.io/email-tool/troubleshooting/
  pause
  exit /b 1
)
echo.
echo Done. Next, in the ChatGPT desktop app:
echo   1. Select Plugins, then Add Marketplace, and type skhan61/email-tool
echo   2. Install email-tool, then close and reopen ChatGPT
echo   3. In Work or Codex mode, ask: add my mailbox
echo.
pause
