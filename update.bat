@echo off
title Update YEnglish Exams on PythonAnywhere

echo ========================================
echo  Updating YEnglish Exams on PythonAnywhere
echo ========================================
echo.

echo [1] Adding changes to Git...
git add .
echo Done.
echo.

echo [2] Committing changes...
git commit -m "Update via update.bat"
echo Done.
echo.

echo [3] Pushing to GitHub...
git push
echo Done.
echo.

echo ========================================
echo  Now you need to update PythonAnywhere.
echo ========================================
echo.
echo Please do these steps manually in PythonAnywhere:
echo.
echo 1. Open a Bash console
echo 2. Run: cd /home/YEnglishExams/YEnglishExams
echo 3. Run: git pull origin main
echo 4. Go to Web tab and click Reload
echo.
echo ========================================
pause