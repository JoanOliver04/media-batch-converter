@echo off
setlocal
cd /d "%~dp0"

set "BUILD_VENV=.build-venv"
if not defined MEDIA_BATCH_DIST_PATH set "MEDIA_BATCH_DIST_PATH=dist"
if not defined MEDIA_BATCH_WORK_PATH set "MEDIA_BATCH_WORK_PATH=build"
if not exist "%BUILD_VENV%\Scripts\python.exe" (
    echo Creating isolated build environment...
    py -3.12 -m venv "%BUILD_VENV%" || goto :error
)

echo Installing pinned build dependencies...
"%BUILD_VENV%\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements-dev.txt || goto :error

echo Running tests...
"%BUILD_VENV%\Scripts\python.exe" -m unittest discover -s tests -v || goto :error

echo Generating Windows version metadata...
"%BUILD_VENV%\Scripts\python.exe" generate_version_info.py || goto :error

echo Building one-folder Windows distribution...
"%BUILD_VENV%\Scripts\python.exe" -m PyInstaller --noconfirm --clean --distpath "%MEDIA_BATCH_DIST_PATH%" --workpath "%MEDIA_BATCH_WORK_PATH%" media_batch_converter.spec || goto :error

if not exist "%MEDIA_BATCH_DIST_PATH%\MediaBatchConverter\MediaBatchConverter.exe" goto :missing
echo Build complete: %MEDIA_BATCH_DIST_PATH%\MediaBatchConverter\MediaBatchConverter.exe
exit /b 0

:missing
echo ERROR: PyInstaller finished without creating the expected executable.
exit /b 1

:error
echo ERROR: Windows build failed. Review the command output above.
exit /b 1
