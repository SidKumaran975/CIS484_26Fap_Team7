@echo off
setlocal
set "DBFILE=%~dp0runtime\assessment.sqlite3"
set "DBBROWSER=%ProgramFiles%\DB Browser for SQLite\DB Browser for SQLite.exe"
if not exist "%DBFILE%" (
    echo Database not found: %DBFILE%
    pause
    exit /b 1
)
if not exist "%DBBROWSER%" (
    echo Open DB Browser for SQLite and select:
    echo %DBFILE%
    pause
    exit /b 1
)
echo Stop the application before editing. Use Write Changes to save edits.
start "" "%DBBROWSER%" "%DBFILE%"
