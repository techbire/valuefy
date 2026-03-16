# Hosting Guide (Render)

This app is now ready to host.

## What was made hosting-friendly
- `server.py` reads `PORT` from environment.
- `server.py` reads `DB_PATH` from environment.
- If `DB_PATH` does not exist, it auto-copies seed DB from `model_portfolio.db`.
- `index.html` now calls API using same origin (`window.location.origin`).

## Deploy Steps
1. Push this folder to a GitHub repository.
2. In Render, choose **New +** -> **Blueprint**.
3. Select your repository (Render will detect `render.yaml`).
4. Deploy.
5. Open the service URL once deployment finishes.

## Important Notes
- Data persists on the mounted Render disk (`/data/model_portfolio.db`).
- On first deploy, DB is seeded automatically from the repository DB.
- On later deploys, existing `/data/model_portfolio.db` is kept.

## Local Run
```bash
python server.py
```
Then open `http://localhost:8765`.
