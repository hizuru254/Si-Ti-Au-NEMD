@echo off
chcp 65001 >nul
title Si-Ti-Au-NEMD v1.1 full anchor (3 seeds x 160k steps)
cd /d D:\si_nemd
echo ============================================================
echo  v1.1 Ti40 anchor FULL
echo  3 seeds, 40k equil + 120k production, bin 2
echo  Estimated time: about 9-10 hours
echo  DO NOT CLOSE THIS WINDOW.
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "D:\si_nemd\anchor\start_anchor11.ps1"
echo.
echo [FINISHED] Check the latest report under:
echo   D:\si_nemd\anchor\workspace\run_vNNN\report.txt
echo.
pause
