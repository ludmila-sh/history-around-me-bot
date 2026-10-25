@echo off

if not exist venv call ./py-install-requirements.cmd

venv\Scripts\python -m src.run_bot
