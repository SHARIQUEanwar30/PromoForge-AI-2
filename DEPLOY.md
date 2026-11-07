# Put PromoForge on GitHub and get a link anyone can open

This guide assumes you have never used GitHub. Every step says what you should see. If something looks different, stop and ask.

**What you will end up with**
* A GitHub page for the project (for your resume).
* A live link like `https://promoforge-yourname.streamlit.app`. Anyone who opens it sees the app directly. No install, no login, no key.

**Time:** about 30 to 40 minutes. **Cost:** free.

---

## Step 0. Prepare a clean folder (important)

Do NOT upload your working folder. It may contain your `.venv`, your `.env` (with your secret key) and Kuku's ZIP.

1. Download `PromoForge-AI.zip` (the public-safe one). Extract it into a NEW folder, for example `Desktop\kuku\PromoForge-AI-public`.
2. Open that folder. You should see `app.py`, `README.md`, `DEPLOY.md`, `requirements.txt`, and folders `promoforge`, `tests`, `docs`, `sample_data`, `tools`.
3. You must NOT see: `.env`, any `.zip` file, `.venv`, `submission_private`, `outputs`. If you do, delete them from this new folder.
4. Optional safety check (shows PASS if no Kuku text is inside): from your working folder run
   `.venv\Scripts\python tools\confidentiality_scan.py --pack "<path to Kuku zip>" --repo "<path to PromoForge-AI-public>"`

## Step 1. Make a GitHub account

1. Go to **github.com** and click **Sign up**. Use your email, make a password and a username (this becomes part of your link, so pick something professional, like `sryan2005`).
2. Check your email and type the verification code.

## Step 2. Create the repository (the project page)

1. Click the **+** at the top right, then **New repository**.
2. Repository name: `PromoForge-AI`.
3. Choose **Public**. (Free hosting needs a public repo.)
4. Do NOT tick "Add a README" or any other box. Click **Create repository**.
5. You see an empty page with a link that says **uploading an existing file**. Click it.

## Step 3. Upload the files

1. Open your clean folder (`PromoForge-AI-public`) in File Explorer. Press **Ctrl + A** to select everything inside it.
2. Drag all of it onto the GitHub page (where it says "Drag files here"). Use Chrome or Edge.
3. Wait until every file is listed. GitHub allows up to 100 files per upload. If it complains, upload in two rounds: first the folders `promoforge` and `tests`, then everything else.
4. Scroll down, leave the message as is, and click **Commit changes**.
5. Check the result: the repo page must list `app.py`, `ui_config.py`, `ui_logic.py`, `requirements.txt`, `README.md`, `DEPLOY.md`, `.gitignore`, and folders `.streamlit`, `promoforge`, `docs`, `sample_data`, `tests`, `tools`.
   * If the `.streamlit` folder is missing, upload it again (Add file, Upload files, drag the `.streamlit` folder). It holds the colours.
   * There must be NO `.env` and no `.zip`. If you see one, open it and delete it with the trash icon, then change your key (Step 7).

## Step 4. Get a free Gemini key (for the AI option)

1. Go to **aistudio.google.com/apikey** and sign in with a Google account.
2. Click **Create API key**, then copy it. Do NOT add any payment method.
3. Never paste this key into a chat, the README or any GitHub file.

## Step 5. Create the live app (Streamlit Community Cloud)

1. Go to **share.streamlit.io**. Click **Continue with GitHub** and allow access.
2. Click **Create app** (it may say **New app**), then choose **Deploy a public app from GitHub**.
3. Fill in:
   * **Repository:** `your-username/PromoForge-AI`
   * **Branch:** `main`
   * **Main file path:** `app.py`
   * **App URL:** pick a name, for example `promoforge-yourname`
4. Click **Advanced settings**.
   * **Python version:** choose 3.12 (3.11 also works).
   * **Secrets:** paste these lines, with your real key between the quotes:
     ```
     PROMOFORGE_API_KEY = "paste-your-key-here"
     PROMOFORGE_PROVIDER = "gemini"
     PROMOFORGE_MAX_CALLS = "30"
     ```
     (`PROMOFORGE_MAX_CALLS` is the most AI calls one run may use. A 50-episode story needs about 16. A lower number protects your free quota.)
   * Click **Save**.
5. Click **Deploy**. Wait 2 to 5 minutes while it installs. You see a log. When it finishes, your app opens.
6. Your link is in the address bar. Copy it.

## Step 6. Test it like a stranger would (very important)

1. Open a **private / incognito window** and paste your link. You must see the PromoForge page without logging in.
2. Pick **Sample story 1**, leave **Rule-based**, press **Run analysis**. You should land on the Dashboard in a few seconds.
3. Go back, pick **Gemini**, press **Run analysis**. It should work without asking for any key and take a minute or two. If a pop-up asks for a key, the Secrets were not saved correctly (see Troubleshooting).
4. Pick **Claude**. A pop-up must say it is not free and ask for a key. Close it.

## Step 7. Put the link in your README

1. On your GitHub repo page, click `README.md`, then the **pencil** icon (Edit).
2. Replace `https://YOUR-APP-NAME.streamlit.app` with your real link (two places in the first lines).
3. Click **Commit changes**.
4. Use that GitHub link and the live link in your resume and in your Kuku Drive folder.

---

## Can other people open my link and use it?

Yes. Anyone with the link can open it in any browser. They need no account and no key.
* **Rule-based** always works.
* **Gemini** uses the key you stored privately in Secrets. Visitors never see it. Everyone shares your free daily limit. If it is used up, the app shows a friendly message with the steps to make their own free key. The limit resets at midnight Pacific time (about 1:30 PM India time in winter).
* **OpenAI / Claude** always ask the visitor for their own paid key.
* A free app that nobody opens for a while goes to sleep. The first visitor sees a button like **"Yes, get this app back up"**. Press it and wait about half a minute.
* Do NOT upload Kuku's real episodes to the public link. Use the sample stories for demos. Kuku's pack is for your own laptop only.

## Keep your key safe

* The key lives only in Streamlit's Secrets box. Change it any time: your app, then **Settings**, then **Secrets**.
* If a key ever appears on GitHub or in a chat, delete it at aistudio.google.com/apikey and make a new one.

## Troubleshooting

| What you see | What to do |
|---|---|
| Deploy log says `ModuleNotFoundError` or `No module named ...` | `requirements.txt` is missing or wrong on GitHub. Upload it again. |
| The page is plain white or colours look wrong | The `.streamlit/config.toml` file was not uploaded. Upload the `.streamlit` folder. |
| Gemini asks for a key even though you saved Secrets | Check the lines are exactly as above, with straight quotes. Save, then **Reboot app** in the app menu. |
| "That key did not work" | Copy the whole key again with no spaces, or make a new key. |
| "The free AI limit for today is finished" | Normal. Use Rule-based, wait for the reset, or paste your own free key in the pop-up. |
| App says it is sleeping | Press the wake-up button and wait about 30 seconds. |

## See it on your own laptop first (optional)

Extract the new zip over your old working folder (choose **Replace**; your `.venv` and `.env` stay), then in PowerShell inside that folder:
```
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```
