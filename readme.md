# Tarkov Wiki Lite

A lightweight, open-source desktop companion for Escape from Tarkov, built with Python and PySide6.

## Features

- Quest search with objectives, rewards and dependencies
- Manual quest and objective tracking
- Persistent progress using SQLite
- Separate PvP and PvE progress
- Pinned quests and Home dashboard
- Companion Mode for secondary monitors
- Visual quest guides with image zoom
- Local caching to reduce network usage

## Installation

Requires Python and Windows.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

## Project Status

**Version:** v0.3 — Work in Progress

Planned features include an item database, crafting information, Flea Market prices and expanded visual quest guides.

## Disclaimer

This application is an independent, unofficial companion for Escape from Tarkov.

It does not read game memory, inspect game processes, modify game files, automate gameplay or interact directly with the game client.

Quest progress is entered manually by the user.

Escape from Tarkov is a property of Battlestate Games. Third-party data and images remain subject to their respective licenses.