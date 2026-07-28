@echo off

REM DEPRECATED as a single-file seat config.
REM Seat packs are now radio-specific. Copy the examples instead:
REM
REM   seat-common.example.cmd       → seat-common.cmd
REM   radio-flex50.example.cmd      → radio-flex50.cmd        (Flex 50 MHz)
REM   radio-ic9700-144.example.cmd  → radio-ic9700-144.cmd    (IC-9700 144 MHz)
REM
REM Launchers:
REM   Start-Seat-Flex50.cmd
REM   Start-Seat-IC9700-144.cmd
REM   Start-WimsSeat.cmd [flex50|ic9700-144]
REM
REM This file remains only so older docs/tools that copy seat-config.example.cmd
REM still produce a usable seat-common.cmd-shaped starter.

call "%~dp0seat-common.example.cmd"
