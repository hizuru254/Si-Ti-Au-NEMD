@echo off
chcp 65001 >nul
title Si-Ti-Au-NEMD v1.1 pilot (1 seed x 80k steps)
cd /d D:\si_nemd
echo ============================================================
echo  v1.1 Ti40 anchor PILOT
echo  1 seed, 40k equil + 40k production, bin 2
echo  Estimated time: about 1.5-2 hours
echo  DO NOT CLOSE THIS WINDOW.
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\si_nemd\anchor\start_pilot11.ps1"
echo.
echo [FINISHED] Check the latest report under:
echo   D:\si_nemd\anchor\workspace\run_vNNN\report.txt
echo.
pause
