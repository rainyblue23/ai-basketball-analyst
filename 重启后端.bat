@echo off
chcp 65001 >nul
rem ==========================================================================
rem  ������ˣ��Ƚ���ռ�Ŷ˿ڵľɺ�ˣ������������Զ��������ĺ�ˡ�
rem  --------------------------------------------------------------------------
rem  Ϊʲô��Ҫ����һ���ļ���
rem    scripts\serve_reload.py ����ʾ��һֱд���á��������.bat����������ļ�
rem    ��ǰ���������� ���� �˿ڱ��ɽ���ռ��ʱ��ֱ��˫�����������.bat��ֻ��
rem    ����"�˿��ѱ�ռ��"��Ȼ���½��̰�ʧ�ܡ�����һ��������ʵ��ȵ�����
rem  ע�⣺�з�����������ʱ��Ҫ���� ���� �����������һ���������
rem  Usage:  double-click this file   (optional first argument = port)
rem ==========================================================================
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"

rem ---- 1) locate the dependency folder (deliberately kept out of the repo) ----
set "LIBS="
if defined AIHOOP_LIBS if exist "%AIHOOP_LIBS%" set "LIBS=%AIHOOP_LIBS%"
if not defined LIBS if exist "%~dp0..\aihoop_assets\libs" set "LIBS=%~dp0..\aihoop_assets\libs"
if not defined LIBS if exist "%~dp0aihoop_assets\libs" set "LIBS=%~dp0aihoop_assets\libs"
if not defined LIBS if exist "%~dp0assets\libs" set "LIBS=%~dp0assets\libs"

set "PYTHONPATH=%~dp0src"
if defined LIBS set "PYTHONPATH=%PYTHONPATH%;%LIBS%"

rem ---- 2) env vars the pipeline needs ----
set "YOLO_CONFIG_DIR=%~dp0_tmp\yolo_cfg"
set "TMP=%~dp0_tmp\tmp"
set "TEMP=%TMP%"
set "MPLCONFIGDIR=%~dp0_tmp\mpl"
set "TORCH_HOME=%~dp0_tmp\torch"
if not exist "%YOLO_CONFIG_DIR%" mkdir "%YOLO_CONFIG_DIR%" >nul 2>&1
if not exist "%TMP%" mkdir "%TMP%" >nul 2>&1

rem ---- 3) pick an interpreter: .venv first, then whatever `python` resolves to ----
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"

echo ============================================================
echo   AI Hoop Analyst - restart backend
echo ------------------------------------------------------------
echo   1) ����ռ�Ŷ˿� %PORT% �ľɺ�˽���
echo   2) �����º�ˣ��� src\aihoop\*.py ��Լ 2 ���Զ���Ч��
echo   API docs : http://127.0.0.1:%PORT%/docs
echo   Frontend : http://127.0.0.1:%PORT%/
echo ------------------------------------------------------------
echo   ����������ʱ�벻Ҫ�������ص������ڼ�ֹͣ��ˡ�
echo ============================================================
echo.

"%PY%" -B scripts\serve_reload.py %PORT% --kill-port
pause
