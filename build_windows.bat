@echo off
setlocal
cd /d "%~dp0"

set "BUILD_VENV=.build-venv"
if not exist "%BUILD_VENV%\Scripts\python.exe" (
    echo Creating isolated build environment...
    py -3.12 -m venv "%BUILD_VENV%" || goto :error
)

echo Installing pinned build dependencies...
"%BUILD_VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-dev.txt || goto :error

echo Running tests...
"%BUILD_VENV%\Scripts\python.exe" -m unittest discover -s tests -v || goto :error

echo Building one-folder Windows distribution...
"%BUILD_VENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean media_batch_converter.spec || goto :error

if not exist "dist\MediaBatchConverter\MediaBatchConverter.exe" goto :missing
echo Build complete: %CD%\dist\MediaBatchConverter\MediaBatchConverter.exe
exit /b 0

:missing
echo ERROR: PyInstaller finished without creating the expected executable.
exit /b 1

:error
echo ERROR: Windows build failed. Review the command output above.
exit /b 1
