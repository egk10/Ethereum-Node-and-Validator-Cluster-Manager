@echo off
REM 🚀 Ethereum Validator Manager - Windows Easy Install Script

echo 🚀 Installing Ethereum Validator Cluster Manager for Windows...

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Error: Python not found. Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

REM Install dependencies
echo 🐍 Installing Python dependencies...
pip install click pyyaml requests tabulate colorama pandas numpy

REM Create installation directory
set "INSTALL_DIR=%USERPROFILE%\.local\bin"
set "CONFIG_DIR=%USERPROFILE%\.config\eth-validators"
set "DATA_DIR=%USERPROFILE%\.local\share\eth-validators"

echo 📂 Creating directories...
mkdir "%INSTALL_DIR%" 2>nul
mkdir "%CONFIG_DIR%" 2>nul
mkdir "%DATA_DIR%" 2>nul

REM Copy application files
echo 📦 Installing application files...
xcopy /E /I /Y eth_validators "%DATA_DIR%\eth_validators"

REM Create the wrapper batch file
echo 🔧 Creating eth-validators.bat command...
(
echo @echo off
echo REM Ethereum Validator Cluster Manager Wrapper Script
echo set "APP_DIR=%DATA_DIR%"
echo set "PYTHONPATH=%DATA_DIR%;%%PYTHONPATH%%"
echo cd /d "%%APP_DIR%%"
echo python -m eth_validators %%*
) > "%INSTALL_DIR%\eth-validators.bat"

REM Copy configuration files
if exist "eth_validators\config.yaml" (
    echo ⚙️ Installing configuration...
    copy "eth_validators\config.yaml" "%CONFIG_DIR%\"
    copy "eth_validators\validators_vs_hardware.csv" "%CONFIG_DIR%\"
)

REM Add to PATH if not already there
echo 🔧 Adding to PATH...
setx PATH "%PATH%;%INSTALL_DIR%" >nul

echo.
echo ✅ Installation completed successfully!
echo.
echo 🎯 Quick Start:
echo    eth-validators --help
echo    eth-validators node list
echo    eth-validators performance summary
echo.
echo 📁 Configuration files:
echo    Config: %CONFIG_DIR%\config.yaml
echo    Nodes:  %CONFIG_DIR%\validators_vs_hardware.csv
echo.
echo 🔄 Please restart your Command Prompt or PowerShell
echo    to use the 'eth-validators' command.
echo.
pause
