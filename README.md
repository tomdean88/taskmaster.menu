# Taskmaster Menu

A Jackbox-style party app for a Taskmaster-themed birthday. Guests join from their own phones by scanning a QR code, judge each other's tasks, and watch a live leaderboard on the TV. No app install required.

## How it works

- **Central** (TV): shows the join QR, the current task, and the live leaderboard.
- **Phones**: guests join with a name and selfie, then score performers 1 to 5 during each task.
- **Admin**: the host runs the night from her phone: creates tasks, opens voting, and fixes mistakes.

### Scoring

1. Every judge scores every performer 1 to 5.
2. Each performer's highest and lowest scores are dropped (when there are 5 or more judges), and the rest are summed.
3. Performers are ranked by total and spread across 1 to 5 Taskmaster points. Ties share points.

Points are never stored. They are always calculated from ballots, so correcting a ballot corrects the leaderboard.

## Tech

Python, FastAPI, WebSockets, SQLite, and plain HTML/CSS/JS. No frontend build step.

## Setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# Linux:   source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit .env
```

## Run

```bash
uvicorn app.main:app --reload --env-file .env
```

Health check: http://localhost:8000/health

## Configuration

| Variable | Purpose |
|---|---|
| `ADMIN_PASSWORD` | Password for the admin panel |
| `PUBLIC_URL` | The URL guests use; the join QR code is generated from it |
| `DATA_DIR` | Where the database and photos are stored |