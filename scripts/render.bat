@echo off
setlocal EnableDelayedExpansion
rem ===========================================================================
rem render.bat -- Geometrie exportieren und Praesentationsbilder rendern.
rem
rem Ohne Argument laeuft der komplette Weg: feiner STL-Export ueber TiGL,
rem anschliessend alle Shots in Blender, danach wird die Viewer-Geometrie in
rem der Standardaufloesung wiederhergestellt.
rem
rem   render.bat                  Export (fein) + alle Shots + Viewer-Export
rem   render.bat export           nur feiner Export fuer Renderings
rem   render.bat viewer           nur Viewer-Export (TIGL_DEFLECTION=0.001)
rem   render.bat shots les        nur die genannten Shots rendern
rem   render.bat list             verfuegbare Shots anzeigen
rem   render.bat setup            lxml und pythonocc-core in pixi nachziehen
rem
rem Pfade unten anpassen, falls sich die Repositories verschieben.
rem ===========================================================================

rem --- Konfiguration --------------------------------------------------------
rem TIGL_REPO kann von aussen gesetzt werden, damit dieser Pfad nicht
rem in jeder Arbeitskopie angepasst werden muss:
rem   set TIGL_REPO=C:\dev\tigl && render.bat
if not defined TIGL_REPO set "TIGL_REPO=D:\Entwicklung\Apollo11\tigl"
set "PIXI_ENV=python-internal"
set "BLENDER=blender"

rem Feinheit der Tessellierung. 0.001 ist der Viewer-Wert; fuer Standbilder
rem ist er zu grob, dann zeigen die Domes in Nahaufnahmen Facetten.
set "DEFLECTION_RENDER=0.0005"
set "DEFLECTION_VIEWER=0.001"

rem Blender-Qualitaet. 16 reicht zum Pruefen von Achse und Ausschnitt,
rem 128 fuer die Bilder, die auf die Folien kommen.
set "SAMPLES=128"

rem --- Ableitungen ----------------------------------------------------------
rem %~dp0 ist der Ordner dieser Datei; das Repository liegt eine Ebene darueber,
rem falls sie unter scripts\ abgelegt wird. Beides wird geprueft.
set "REPO=%~dp0"
if exist "%REPO%saturnV.xml" goto :repo_ok
set "REPO=%~dp0..\"
if exist "%REPO%saturnV.xml" goto :repo_ok
echo FEHLER: saturnV.xml weder in "%~dp0" noch eine Ebene darueber gefunden.
exit /b 1
:repo_ok
for %%I in ("%REPO%") do set "REPO=%%~fI"
if "%REPO:~-1%"=="\\" set "REPO=%REPO:~0,-1%"

set "EXPORT_SCRIPT=%REPO%\scripts\export_models.py"
set "RENDER_SCRIPT=%REPO%\scripts\render_saturnv.py"
set "MODEL_DIR=%REPO%\web\public\models"
set "FIGURE_DIR=%REPO%\figures\render"

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=all"

rem --- Vorbedingungen -------------------------------------------------------
if not exist "%TIGL_REPO%\pixi.toml" (
    echo FEHLER: keine pixi.toml in "%TIGL_REPO%".
    echo Passe TIGL_REPO oben in dieser Datei an.
    exit /b 1
)
if not exist "%EXPORT_SCRIPT%" (
    echo FEHLER: export_models.py nicht gefunden: "%EXPORT_SCRIPT%"
    exit /b 1
)

if /i "%ACTION%"=="setup"  goto :setup
if /i "%ACTION%"=="build"  goto :build
if /i "%ACTION%"=="export" goto :export_fine
if /i "%ACTION%"=="viewer" goto :export_viewer
if /i "%ACTION%"=="list"   goto :list
if /i "%ACTION%"=="shots"  goto :shots
if /i "%ACTION%"=="all"    goto :all
echo FEHLER: unbekannte Aktion "%ACTION%".
echo Erlaubt: export ^| viewer ^| shots ^| list ^| setup ^| build ^| (leer = alles)
exit /b 1

rem ===========================================================================
:setup
rem lxml und pythonocc-core sind nicht Teil der TiGL-Standardumgebung.
rem
rem "pixi add" erwartet --feature, nicht -e; -e gibt es nur bei "pixi run".
rem Aeltere pixi-Versionen akzeptierten -e auch hier, daher steht es noch so
rem in build_tigl.sh. Falls das Feature in TiGLs pixi.toml anders heisst als
rem das Environment, zeigt "pixi info" die Zuordnung.
rem
rem Achtung: das schreibt in pixi.toml und pixi.lock des TiGL-Checkouts.
rem Diese Aenderung gehoert nicht in einen TiGL-Commit.
echo.
echo === pixi-Umgebung ergaenzen ===
pushd "%TIGL_REPO%"
if not "%ERRORLEVEL%"=="0" exit /b 1

call pixi add --feature %PIXI_ENV% pythonocc-core lxml
set "RC=!ERRORLEVEL!"

if not "!RC!"=="0" (
    echo.
    echo Hinweis: --feature %PIXI_ENV% hat nicht funktioniert, versuche --environment.
    call pixi add --environment %PIXI_ENV% pythonocc-core lxml
    set "RC=!ERRORLEVEL!"
)

popd
if not "%RC%"=="0" (
    echo.
    echo FEHLER: pixi add fehlgeschlagen ^(Code %RC%^).
    echo Pruefe mit "pixi info" im TiGL-Ordner, wie Feature und Environment heissen,
    echo und passe PIXI_ENV oben in dieser Datei an.
    exit /b %RC%
)
echo.
echo Fertig. pixi.toml und pixi.lock im TiGL-Repo wurden veraendert.
echo.
echo Falls danach "No module named 'tigl3'" kommt, fehlen die Bindings:
echo   render.bat build
exit /b 0

rem ===========================================================================
:build
rem tigl3 ist kein Conda-Paket, sondern entsteht beim Bauen von TiGL und wird
rem in die pixi-Umgebung installiert. Ein "pixi install" oder "pixi clean"
rem baut die Umgebung aus dem Lockfile neu auf und entfernt die Bindings
rem wieder -- dann ist dieser Schritt zu wiederholen.
echo.
echo === TiGL-Bindings bauen ^(dauert einige Minuten^) ===
pushd "%TIGL_REPO%"
if not "%ERRORLEVEL%"=="0" exit /b 1
call pixi run -e %PIXI_ENV% configure
set "RC=!ERRORLEVEL!"
if "!RC!"=="0" (
    call pixi run -e %PIXI_ENV% install
    set "RC=!ERRORLEVEL!"
)
if "!RC!"=="0" (
    echo.
    echo === Pruefen ===
    call pixi run -e %PIXI_ENV% python -c "import tigl3, lxml; print(tigl3.__file__)"
    set "RC=!ERRORLEVEL!"
)
popd
if not "%RC%"=="0" (
    echo.
    echo FEHLER: Bindings-Bau fehlgeschlagen ^(Code %RC%^).
    echo Task-Namen pruefen mit "pixi task list" im TiGL-Ordner.
    exit /b %RC%
)
exit /b 0

rem ===========================================================================
:export_fine
call :run_export "%DEFLECTION_RENDER%" "Renderings"
exit /b %ERRORLEVEL%

rem ===========================================================================
:export_viewer
call :run_export "%DEFLECTION_VIEWER%" "Web-Viewer"
exit /b %ERRORLEVEL%

rem ===========================================================================
:list
call :check_blender
if not "%ERRORLEVEL%"=="0" exit /b 1
"%BLENDER%" --background --python "%RENDER_SCRIPT%" -- --list
exit /b %ERRORLEVEL%

rem ===========================================================================
:shots
if "%~2"=="" (
    echo FEHLER: Aktion "shots" braucht Shot-Namen, z. B.:
    echo   render.bat shots les,closeup_vessel
    exit /b 1
)
call :check_blender
if not "%ERRORLEVEL%"=="0" exit /b 1
call :check_manifest
if not "%ERRORLEVEL%"=="0" exit /b 1
call :run_blender "--shots %~2"
exit /b %ERRORLEVEL%

rem ===========================================================================
:all
call :run_export "%DEFLECTION_RENDER%" "Renderings"
if not "%ERRORLEVEL%"=="0" exit /b %ERRORLEVEL%

call :check_blender
if not "%ERRORLEVEL%"=="0" exit /b 1
call :run_blender ""
set "RENDER_RC=%ERRORLEVEL%"

rem Der Viewer-Export laeuft auch dann, wenn Blender gescheitert ist: sonst
rem bleibt das Modellverzeichnis in der feinen Tessellierung zurueck und der
rem naechste npm run dev laedt zaeh.
echo.
echo === Viewer-Geometrie wiederherstellen ===
call :run_export "%DEFLECTION_VIEWER%" "Web-Viewer"

if not "%RENDER_RC%"=="0" (
    echo.
    echo WARNUNG: Blender endete mit Code %RENDER_RC%.
    exit /b %RENDER_RC%
)
echo.
echo Bilder liegen in "%FIGURE_DIR%".
exit /b 0

rem ===========================================================================
rem Unterprogramme
rem ===========================================================================

:run_export
rem %~1 = Deflection, %~2 = Beschriftung
echo.
echo === STL-Export ^(%~2, Deflection %~1^) ===
pushd "%TIGL_REPO%" || exit /b 1
set "TIGL_DEFLECTION=%~1"
call pixi run -e %PIXI_ENV% python "%EXPORT_SCRIPT%"
set "RC=!ERRORLEVEL!"
set "TIGL_DEFLECTION="
popd
if not "%RC%"=="0" (
    echo.
    echo FEHLER: Export fehlgeschlagen ^(Code %RC%^).
    echo Fehlt lxml oder pythonocc-core:  render.bat setup
    echo Fehlt tigl3:                     render.bat build
    exit /b %RC%
)
exit /b 0

:run_blender
rem %~1 = zusaetzliche Argumente fuer render_saturnv.py
echo.
echo === Blender ^(%SAMPLES% Samples^) ===
"%BLENDER%" --background --python "%RENDER_SCRIPT%" -- --samples %SAMPLES% %~1
exit /b %ERRORLEVEL%

:check_blender
if not exist "%RENDER_SCRIPT%" (
    echo FEHLER: render_saturnv.py nicht gefunden: "%RENDER_SCRIPT%"
    exit /b 1
)
where %BLENDER% >nul 2>&1
if not "%ERRORLEVEL%"=="0" (
    echo FEHLER: "%BLENDER%" nicht im PATH.
    echo Setze BLENDER oben in dieser Datei auf den vollen Pfad, z. B.
    echo   set "BLENDER=C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"
    exit /b 1
)
exit /b 0

:check_manifest
if not exist "%MODEL_DIR%\models.json" (
    echo FEHLER: models.json fehlt in "%MODEL_DIR%".
    echo Zuerst exportieren:  render.bat export
    exit /b 1
)
exit /b 0
