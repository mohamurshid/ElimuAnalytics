@echo off
REM Elimu Analytics task runner (Windows).
REM   tasks setup   create the venv and install dependencies
REM   tasks test    run the test suite
REM   tasks lint    run ruff
REM   tasks fix     run ruff with autofix
REM   tasks seed    rebuild the schema and demonstration data (--reset to drop first)
REM   tasks newschool  create a school and its first head teacher (asks, or --school --type --head-name --head-email)
REM   tasks extract rebuild the curriculum corpus JSON from the KICD PDFs
REM   tasks ingest  load the KICD curriculum corpus into curriculum_chunk
REM   tasks check   verify pgvector retrieval against numpy on the stored vectors
REM   tasks query   retrieve against the corpus: tasks query "text" "Grade 5" "Science and Technology"
REM   tasks run     start the backend development server
REM   tasks web     start the Next.js frontend (http://localhost:3000)
REM   tasks tunnel  open the PUBLIC_URL ngrok address to the frontend, for phones (UAT)
REM   tasks webci   frontend lint, typecheck and build
REM   tasks ci      everything CI runs, locally, before you push
REM   tasks gen     measure question generation (plan only; add --go to call the API)
REM   tasks psy     measure model fit (RMSEA), item fit and criterion validity (F1) on the Riiid sample

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

:seed
call .venv\Scripts\activate
cd backend
python -m app.seed %2 %3
goto end

:newschool
call .venv\Scripts\activate
cd backend
set "ARGS="
:newschool_args
shift
if "%~1"=="" goto newschool_run
set ARGS=%ARGS% "%~1"
goto newschool_args
:newschool_run
python -m app.new_school %ARGS%
goto end

:extract
call .venv\Scripts\activate
python spike\build_curriculum_corpus.py --extract %2 %3
goto end

:ingest
call .venv\Scripts\activate
cd backend
python -m app.ingest_curriculum %2 %3
goto end

:check
call .venv\Scripts\activate
cd backend
python -m app.retrieval --check %2 %3
goto end

:query
call .venv\Scripts\activate
cd backend
python -m app.retrieval --query %2 --grade %3 --area %4 --top-k 8 --no-floor
goto end

:gen
call .venv\Scripts\activate
python spike\generation_at_scale.py %2 %3 %4
goto end

:psy
call .venv\Scripts\activate
set "PSYDATA=%~2"
if "%PSYDATA%"=="" set "PSYDATA=data\riiid_sample_by_users.csv"
python spike\psychometric_validation.py --data "%PSYDATA%" %3 %4 %5 %6
goto end

:run
call .venv\Scripts\activate
cd backend
python -m uvicorn app.main:app --reload --port 8000
goto end

:web
cd frontend
npm run dev
goto end

:tunnel
if "%PUBLIC_URL%"=="" (
  echo PUBLIC_URL is not set. Run once:  setx PUBLIC_URL https://your-name.ngrok-free.app
  echo then open a new terminal. See docs\RUNBOOK.md, "Phones during UAT".
  exit /b 1
)
where ngrok >nul 2>nul || (
  echo ngrok is not installed or not on PATH. See docs\RUNBOOK.md, "Phones during UAT".
  exit /b 1
)
echo Phones open %PUBLIC_URL%  - keep this window open; Ctrl+C closes the address.
ngrok http --url=%PUBLIC_URL% 3000
goto end

:webci
cd frontend
call npm run lint || goto fail
call npm run typecheck || goto fail
call npm run build || goto fail
echo.
echo Frontend checks passed.
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
echo Usage: tasks [setup^|test^|lint^|fix^|seed^|newschool^|extract^|ingest^|check^|query^|gen^|run^|web^|tunnel^|webci^|ci]
goto end

:end
endlocal
