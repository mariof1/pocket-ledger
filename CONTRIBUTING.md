# Contributing

Open a focused pull request from a feature branch. Describe the behavior change, any SQLite migration, and how you checked it. `main` is the release branch; `dev` is available for integration work. The maintainer keeps both branches in sync and creates semantic-version tags from `main`.

## Run the app from source

Create a Python virtual environment and install the pinned dependencies in `requirements.txt`. On Windows:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

On macOS or Linux, use `.venv/bin/python` instead of `.venv\Scripts\python.exe`. Open `http://127.0.0.1:5000` on the same computer. Local data is stored in `instance/`, which is ignored by Git.

## Check your change

Run the server and migration tests with your virtual environment's Python, then run the browser tests with Node.js:

```text
.venv\Scripts\python.exe -m unittest -v test_app.py test_ldap_auth.py test_migrations.py
node --test test_mortgage_guide.js
```

Also run `node --check` on any changed `static/*.js` file. GitHub Actions checks both supported Python versions, all browser scripts, and a Docker build with persistent-data smoke tests. Keep real account exports, databases, credentials and signing keys out of Git.

Public pull requests retain their contributors' authorship; release-branch commits in this repository are made by the `mariof1` account.
