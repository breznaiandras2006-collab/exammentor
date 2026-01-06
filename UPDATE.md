# ExamMentor — Update & Run (Replit + GitHub)

## Daily flow (recommended)
1) Pull latest code:
```bash
cd ~/workspace
git pull
```

2) Install deps (only if something changed):
```bash
pip install -r requirements.txt --no-cache-dir
```

3) Run:
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 3000
```

## If you received a ZIP snapshot
> Do NOT commit `uploads/` or `app.db` to GitHub.

1) Upload ZIP into Replit (Files panel) to `~/workspace`

2) Unzip (overwrite):
```bash
cd ~/workspace
unzip -o ExamMentor_*.zip
```

3) Make sure local data is ignored:
- `uploads/`
- `app.db`
- `.pythonlibs/`

If Git already tracks them:
```bash
git rm -r --cached uploads app.db .pythonlibs 2>/dev/null || true
```

4) Commit + push:
```bash
git add .
git commit -m "Update: <short message>"
git push
```
