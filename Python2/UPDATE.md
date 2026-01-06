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

## PDF Tools v2 notes
- Better validation (no more 500 on bad page ranges)
- Field values persist after submit
- Quick buttons: `1..N`, `N..1`, `Törlés` (auto-fill based on selected document's page count)

## Study v1 notes
- Study tab is now functional (no AI yet)
  - Generate flashcards from Notes (patterns: `Term: def`, `Term - def`, `Q:` / `A:`)
  - Session Q/A review (Leitner boxes 1..5)
  - Mini-Quiz multiple choice
  - Stats (box distribution + last 50 accuracy + weak cards)

### Tip
If you already have notes, first run:
- **Study → Generálás**
Then:
- **Session** or **Mini-Quiz**


## Study v1.3 notes
- Fix: PDF/notes wrapped lines no longer cut answers mid-sentence (better multi-line Q/A extraction)
- Fix: removed duplicate FastAPI decorators (cleaner routing)
- Added `.gitignore` so `uploads/` + `app.db` won’t be committed accidentally
