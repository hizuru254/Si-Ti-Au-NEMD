@echo off
chcp 65001 >nul
title Si-Ti-Au-NEMD anchor (3 seeds x 120k steps)
cd /d D:\si_nemd
echo ============================================================
echo  Si/Ti/Au/Ti/Si flat anchor
echo  3 seeds x 120,000 steps, serial
echo  Estimated time: about 5.7 hours
echo  DO NOT CLOSE THIS WINDOW.
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\si_nemd\anchor\start_anchor.ps1"
echo.
echo [FINISHED] Check the latest report under:
echo   D:\si_nemd\anchor\workspace\run_vNNN\report.txt
echo.
pause
