@echo off
rem email-tool setup for ChatGPT desktop and Codex on Windows: installs uv, which runs email-tool.
rem The same command as the Install page in the documentation, so nothing needs typing.
echo Installing uv, the program that runs email-tool. This takes about a minute.
echo.
rem Windows PowerShell by its full path, with PSModulePath cleared: started from PowerShell 7 it would
rem inherit PowerShell 7's module folders and fail to load its own modules (#170).
set "PSModulePath="
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -ExecutionPolicy ByPass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"
if errorlevel 1 (
  echo.
  echo The installation did not finish. See https://skhan61.github.io/email-tool/troubleshooting/
  pause
  exit /b 1
)
echo.
echo Done. Next, in the ChatGPT desktop app:
echo   1. If ChatGPT is open, quit it: right-click its icon next to the clock and select Exit.
echo      Closing the window is not enough. Then open ChatGPT again.
echo   2. Select Plugins, then Add a marketplace, and type skhan61/email-tool
echo   3. Install email-tool, then in Work or Codex mode ask: add my mailbox
echo.
pause
