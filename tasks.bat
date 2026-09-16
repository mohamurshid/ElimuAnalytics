@echo off
REM Elimu Analytics task runner (Windows).
REM   tasks setup   create the venv and install dependencies
REM   tasks test    run the test suite
REM   tasks lint    run ruff
REM   tasks fix     run ruff with autofix
REM   tasks run     start the development server
REM   tasks ci      everything CI runs, locally, before you push

setlocal
if "%1"=="" goto help
goto %1 2>nul || goto help

:setup
python -m venv .venv
call .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r backend\requirements-dev.txt
echo.
echo Setup complete. Activate with: .venv\Scripts\activate
goto end

:test
call .venv\Scripts\activate
pytest
goto end

:lint
call .venv\Scripts\activate
ruff check .
goto end

:fix
call .venv\Scripts\activate
ruff check --fix .
goto end

:run
call .venv\Scripts\activate
cd backend
python -m uvicorn app.main:app --reload --port 8000
goto end

:ci
call .venv\Scripts\activate
ruff check . || goto fail
pytest || goto fail
echo.
echo CI checks passed. Safe to push.
goto end

:fail
echo.
echo CI checks FAILED. Fix before pushing.
exit /b 1

:help
echo Usage: tasks [setup^|test^|lint^|fix^|run^|ci]
goto end

:end
endlocal
