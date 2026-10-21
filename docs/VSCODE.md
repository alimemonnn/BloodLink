# Run BloodLink in VS Code (Windows, Mac or Linux)

## One-time setup
1. Install **Python 3.12 or newer** from python.org (tick "Add python.exe to PATH") and **VS Code**.
2. VS Code: **File > Open Folder...** and choose the folder that contains `app.py`.
3. Click **Install** when VS Code offers the recommended extensions (Python, Python Debugger), or install "Python" by Microsoft.
4. Open the terminal with **Ctrl + `** (the key above Tab) and run:
   ```
   python -m venv venv
   venv\Scripts\activate          (Mac/Linux: source venv/bin/activate)
   pip install -r requirements.txt
   python seed.py                 (demo data; only once, only on an empty database)
   ```
   Or run the task **Terminal > Run Task > BloodLink: create venv and install requirements**.
5. Press **Ctrl+Shift+P**, type **Python: Select Interpreter**, choose the one inside `venv`.
   The bottom-left of VS Code should then show `('venv': venv)`.

## Every time
Press **F5** and choose **BloodLink: run the website**, or type `python app.py` in the terminal.
Then **Ctrl+click** the address in the terminal, or open http://127.0.0.1:5000. Stop with **Shift+F5** (or Ctrl+C).

| Launch configuration (F5 menu) | Use it for |
|---|---|
| BloodLink: run the website | normal run |
| BloodLink: run with auto-reload | edit a file, save, refresh the browser |
| BloodLink: debug with breakpoints | click the grey margin next to a line, use the site, VS Code stops there |
| BloodLink: add demo data | the same as `python seed.py` |
| BloodLink: run background jobs once | reminders, escalation, queued messages |
| BloodLink: run all tests | needs `pip install -r requirements-dev.txt` first (task: "install test tools") |

Tip: **Ctrl+Shift+P > Simple Browser: Show** opens the site inside VS Code.

## Demo logins (after seeding)
Admin `admin@bloodlink.com` / `Admin123` · Hospital `civil@sukkurhospital.com` / `Hospital123` ·
Donor `bilal@example.com` / `Donor123` · Patient `ayesha@example.com` / `Patient123`.
Pick the role on the login page first. For chat, use a normal window and a private window.

## Problems
| What you see | Fix |
|---|---|
| `venv\Scripts\Activate.ps1 cannot be loaded because running scripts is disabled` | In the terminal run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, or switch the terminal to **Command Prompt** (the `v` beside the + button > Command Prompt). |
| `ModuleNotFoundError: No module named 'flask'` (or `dotenv`, `segno` ...) | Wrong interpreter or packages missing. Select the `venv` interpreter (step 5), then `pip install -r requirements.txt`. |
| `'python' is not recognized` | Reinstall Python with "Add to PATH" ticked, or use `py -m venv venv`. |
| `Address already in use` / port 5000 busy | Close the other run, or change `"PORT": "5000"` to `"5001"` in `.vscode/launch.json` and open that port. |
| `seed.py` says the database is not empty | It already has data. Delete `database.db` (or your `DATABASE_URL` database) only if you want to start over. |
| Browser shows an old page after editing | Use the **auto-reload** configuration and press Ctrl+F5 in the browser. |
| No email arrives | See [EMAIL_SETUP.md](EMAIL_SETUP.md). |
