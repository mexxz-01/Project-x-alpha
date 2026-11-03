@echo off
REM =========================================================================
REM  Project-X-Nano: Native C/C++ Engine Build Script
REM  Compiles remotepc_core.c into remotepc_core.dll using GCC or MSVC
REM =========================================================================

setlocal
cd /d "%~dp0"

echo [*] Checking for available C/C++ compiler...

where gcc >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [+] GCC found. Compiling remotepc_core.dll...
    gcc -O3 -shared -Wall remotepc_core.c -o remotepc_core.dll -lgdi32 -luser32 -lkernel32 -lwinmm
    if %ERRORLEVEL% EQU 0 (
        echo [OK] remotepc_core.dll built successfully via GCC!
        copy /y remotepc_core.dll ..\remotepc_core.dll >nul
        goto :done
    )
)

where cl >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [+] MSVC cl found. Compiling remotepc_core.dll...
    cl /O2 /LD remotepc_core.c /Fe:remotepc_core.dll user32.lib gdi32.lib kernel32.lib winmm.lib
    if %ERRORLEVEL% EQU 0 (
        echo [OK] remotepc_core.dll built successfully via MSVC!
        copy /y remotepc_core.dll ..\remotepc_core.dll >nul
        goto :done
    )
)

echo [!] No C compiler found in PATH.
echo [!] Note: The Python native_bridge will automatically use direct 64-bit Win32 C types.
:done
endlocal
