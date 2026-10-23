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

## How it works

- **Central** (`/central`, on the TV): lobby with the join QR, live leaderboards, and results after each task.
- **Phones** (`/join`, then `/play`): guests join with a name and selfie, judge the other group's tasks, and check the leaderboard and their own results.
- **Admin** (`/admin`): the host runs the night from her phone: tasks, voting, the TV screen, players, ballots, and point adjustments.

### Scoring

1. Every judge (the group not performing) scores every performer 1 to 5 stars.
2. Each performer's single highest and lowest scores are dropped when there are 5 or more judges, and the rest are summed.
3. Performers are ranked by total using competition ranking (ties share a rank, and the next rank skips: 1, 1, 3), then spread evenly across 5 to 1 Taskmaster points.
4. Disqualified performers get 0. Performers who sat out get nothing for that task.
5. The host can award bonus points or penalties at any time.

Points are never stored. They are always calculated from ballots, so correcting a ballot corrects the leaderboard.

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

## Tests

```bash
pytest
```

Every test runs against a fresh, temporary database, so tests never touch real party data.