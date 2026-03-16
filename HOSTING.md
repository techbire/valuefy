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
- Current `render.yaml` is configured for **free tier** (no disk support).
- Free tier uses `/tmp/model_portfolio.db`, so data is **ephemeral** and may reset on redeploy/restart.
- On first deploy, DB is seeded automatically from the repository DB.

## If You Need Persistent Data
- Change service plan to a paid plan (for example, Starter).
- Add a `disk` block in `render.yaml` and set `DB_PATH` to `/data/model_portfolio.db`.

## Local Run
```bash
python server.py
```
Then open `http://localhost:8765`.
