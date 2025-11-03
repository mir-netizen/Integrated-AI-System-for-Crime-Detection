@echo off
REM Clip-Based Analysis System Startup Script
REM This script starts all services for clip-based image/video analysis

echo ===============================================================================
echo CLIP-BASED ANALYSIS SYSTEM
echo ===============================================================================
echo.

REM Check if input file is provided
if "%~1"=="" (
    echo ERROR: No input file specified!
    echo.
    echo Usage: start_clip_analysis.bat ^<image_or_video_file^>
    echo.
    echo Examples:
    echo   start_clip_analysis.bat img.jpg
    echo   start_clip_analysis.bat test_video.mp4
    echo.
    echo Supported formats:
    echo   Images: .jpg, .jpeg, .png, .gif, .bmp
    echo   Videos: .mp4, .avi, .mov, .mkv
    echo.
    pause
    exit /b 1
)

set INPUT_FILE=%~1

REM Check if file exists
if not exist "%INPUT_FILE%" (
    echo ERROR: File not found: %INPUT_FILE%
    echo.
    pause
    exit /b 1
)

echo Input File: %INPUT_FILE%
echo.
echo Starting services...
echo ===============================================================================
echo.

REM Start Kafka (if not already running)
echo [1/9] Checking Kafka...
REM Uncomment if you need to start Kafka
REM start "Kafka Zookeeper" cmd /k "cd kafka && bin\windows\zookeeper-server-start.bat config\zookeeper.properties"
REM timeout /t 5
REM start "Kafka Server" cmd /k "cd kafka && bin\windows\kafka-server-start.bat config\server.properties"
REM timeout /t 10

REM Start Clip Analysis Service FIRST - MUST be subscribed before services publish
echo [2/9] Starting Clip Analysis Service (MUST START FIRST)...
start "Clip Analysis" cmd /k "python decision\decision_clip.py"
echo Waiting for Clip Analysis to fully subscribe (8 seconds)...
timeout /t 8

REM Start Output Viewer
echo [3/9] Starting Output Viewer...
start "Output Viewer" cmd /k "python output_clip.py"
timeout /t 2

REM Start Pose Service (Docker)
@REM echo [4/9] Starting Pose Service (Docker)...
@REM start "Pose Service" cmd /k "cd pose && docker-compose up"
@REM timeout /t 5

REM Start Object Detection Service
echo [5/9] Starting Object Detection Service...
start "Object Detection" cmd /k "python object\object.py"
timeout /t 2

REM Start Object Detection1 Service (Weapon Detection)
echo [6/9] Starting Weapon Detection Service...
start "Weapon Detection" cmd /k "python object\object1.py"
timeout /t 2

REM Start Face Service
echo [7/9] Starting Face Service...
start "Face Service" cmd /k "python face\face.py"
timeout /t 2

REM Start Scene Service
echo [8/9] Starting Scene Service...
start "Scene Service" cmd /k "python scene\blip.py"
timeout /t 2

REM Start Interaction Service
echo [9/9] Starting Interaction Service...
start "Interaction Service" cmd /k "python interaction\interaction.py"
timeout /t 2

REM Wait for all services to initialize
echo.
echo Waiting for all analysis services to fully initialize (10 seconds)...
timeout /t 20

REM Process the input file
echo.
echo ===============================================================================
echo All services started! Now processing input file...
echo ===============================================================================
echo.

python video_demo.py "%INPUT_FILE%"

echo.
echo ===============================================================================
echo INPUT FILE PROCESSING COMPLETE
echo ===============================================================================
echo.
echo Check the "Output Viewer" window for analysis results!
echo.
echo All service windows will remain open for reviewing.
echo Press any key to see instructions for stopping services...
pause

echo.
echo ===============================================================================
echo TO STOP ALL SERVICES:
echo ===============================================================================
echo 1. Close each service window manually, OR
echo 2. Run: taskkill /F /FI "WindowTitle eq *Service*"
echo 3. Stop Docker pose service: cd pose ^&^& docker-compose down
echo ===============================================================================
echo.
