# BugFix Developer

Full-stack portfolio website for advertising bug-fixing and debugging services.

## Project structure

```text
bugfix_developer/
├── backend/
│   ├── app.py
│   ├── requirements.txt
│   ├── .env.example
│   └── __init__.py
├── frontend/
│   └── static/
│       ├── index.html
│       ├── admin.html
│       ├── styles.css
│       ├── app.js
│       └── admin.js
├── .gitignore
└── README.md
```

- `frontend/`: public landing page, admin interface, styles, and browser JavaScript.
- `backend/`: FastAPI API, login/session handling, SQLite database, and image upload management.
- `backend/data/`: created automatically at runtime for the database and uploaded images (unless `DATA_DIR` is set).

## Requirements
- Python 3.11 or newer
- Windows PowerShell

## Run locally (Windows PowerShell)

From the project root:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r .\backend\requirements.txt
Copy-Item .\backend\.env.example .\backend\.env
notepad .\backend\.env
```

Change `ADMIN_PASSWORD` and `SECRET_KEY` in `backend\.env`. Then start the server from the project root:

```powershell
uvicorn backend.app:app --reload
```

Open:
- Public site: http://127.0.0.1:8000
- Admin panel: http://127.0.0.1:8000/admin
- API docs: http://127.0.0.1:8000/docs

The backend reads environment variables from the process environment. For local `.env` convenience, export the variables before running Uvicorn, or install `python-dotenv` and load `backend/.env` in the app. The simplest reliable setup for this starter is to set the four variables in the current PowerShell session before starting Uvicorn:

```powershell
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "replace-with-a-long-unique-password"
$env:SECRET_KEY = "replace-with-a-long-random-secret"
$env:DATA_DIR = ".\backend\data"
uvicorn backend.app:app --reload
```

If you use the environment variables in the PowerShell session, they take precedence over the `.env` file.

## Publish a case study
1. Open `/admin`.
2. Sign in using the configured admin credentials.
3. Enter the title, technology, problem, diagnosis, solution, and result.
4. Upload up to six screenshots.
5. Choose whether to publish immediately or save as a draft.

## Production notes
- Set `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `SECRET_KEY`, `DATA_DIR`, and `COOKIE_SECURE=true` as environment variables on your hosting provider.
- Keep `backend/data` on a persistent disk/volume, or migrate SQLite and uploads to managed persistent services. Ephemeral filesystems may lose data after redeploys or restarts.
- The contact form currently opens the visitor's email application using a `mailto:` link. Replace `hello@example.com` in `frontend/static/app.js` with the business email address, or connect a server-side contact form.
- Do not upload screenshots containing customer names, emails, tokens, passwords, API keys, private URLs, or other confidential data. Redact them first.
- Before production, add rate limiting, backups, and stronger upload controls such as image re-encoding.
# BugFixDeveloper
