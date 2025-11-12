@echo off
REM ============================================================================
REM Clip-Based Analysis System with Action Recognition
REM Enhanced version with 7 AI services
REM ============================================================================

echo.
echo ================================================================================
echo  CLIP ANALYSIS SYSTEM - ENHANCED WITH ACTION RECOGNITION
echo ================================================================================
echo.
echo Starting services in optimized order...
echo.


REM ============================================================================
REM Step 1: Start Decision Service FIRST (needs to subscribe before data arrives)
REM ============================================================================
echo [1/9] Starting Decision Service (LLM aggregator)...
start "Decision Service" cmd /k "python decision\decision_clip.py"
timeout /t 8 /nobreak >nul
echo       ✓ Decision service started (waiting 8s for subscription)
echo.

REM ============================================================================
REM Step 2: Start Output Service
REM ============================================================================
echo [2/9] Starting Output Service (results display)...
start "Output Service" cmd /k "python output_clip.py"
timeout /t 3 /nobreak >nul
echo       ✓ Output service started
echo.

REM ============================================================================
REM Step 3: Start AI Services (parallel)
REM ============================================================================
echo [3/9] Starting Object Detection Service (general)...
start "Object Detection" cmd /k "python object\object.py"
timeout /t 2 /nobreak >nul

echo [4/9] Starting Weapon Detection Service...
start "Weapon Detection" cmd /k "python object\object1.py"
timeout /t 2 /nobreak >nul

echo [5/9] Starting Facial Expression Service...
start "Facial Expression" cmd /k "python face\face.py"
timeout /t 2 /nobreak >nul

echo [6/9] Starting Scene Understanding Service...
start "Scene Understanding" cmd /k "python scene\blip.py"
timeout /t 2 /nobreak >nul

echo [7/9] Starting Interaction Analysis Service...
start "Interaction Analysis" cmd /k "python interaction\interaction.py"
timeout /t 2 /nobreak >nul

echo [8/9] Starting Action Recognition Service (NEW!)...
start "Action Recognition" cmd /k "python action\action.py"
timeout /t 2 /nobreak >nul

echo       ✓ All AI services started
echo.

REM ============================================================================
REM Step 4: Wait for services to initialize
REM ============================================================================
echo Waiting for all services to initialize...
timeout /t 25 /nobreak >nul
echo       ✓ Services ready
echo.


echo ================================================================================
echo  ALL SERVICES STARTED SUCCESSFULLY
echo ================================================================================
echo.
echo Watch the following windows for results:
echo   • Decision Service    - Clip analysis and LLM reasoning
echo   • Output Service      - Final verdicts (color-coded)
echo   • Action Recognition  - Detected actions (fighting, assault, etc.)
echo   • Video Processing    - Frame extraction progress
echo.
echo Results will also be saved to: clip_analysis_results.json
echo.
echo Press any key to stop all services...
pause >nul

REM ============================================================================
REM Cleanup
REM ============================================================================
echo.
echo Stopping all services...
taskkill /FI "WINDOWTITLE eq Decision Service*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Output Service*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Object Detection*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Weapon Detection*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Facial Expression*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Scene Understanding*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Interaction Analysis*" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Action Recognition*" /F >nul 2>&1


echo.
echo All services stopped.
echo.
