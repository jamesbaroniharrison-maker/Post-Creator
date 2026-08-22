# Migration: handing this off from your PC to hers

Scope, confirmed with you directly: **the architecture doesn't change at all** -
self-hosted Ollama, SQLite, the `.bat` launcher, Windows Task Scheduler, all exactly as
they run on your machine today. This is a *relocation + ownership handoff*, not a
redesign. No Render, no Neon, no cloud hosting - that was floated and explicitly ruled
out in favour of keeping everything local on her PC.

What actually changes: **who owns the accounts** this depends on, and **which physical
computer it runs on**.

---

## 1. What "accounts" actually means here

Nothing in this stack needs a "hosting" account (no Render/Neon/Vercel/etc. - it's not
deployed anywhere, it just runs as a local Windows app). The accounts that matter are:

| Account | What it's for | Does she need her own? |
|---|---|---|
| **GitHub** | Owns the source code, version history | **Yes, required** - the one you explicitly asked about ("how to add myself as a collaborator") |
| **Google AI Studio (Gemini)** | `GEMINI_API_KEY` - research scoring + photo captioning | **Yes, required** |
| **Tavily** | `TAVILY_API_KEY` - the actual web search for research | **Yes, required** |
| **Gmail** | `EMAIL_ADDRESS` / `EMAIL_APP_PASSWORD` - sends the two reminder emails | **Yes, required** |
| Ollama | Runs the drafting model locally | No account - it's just installed software |
| The dashboard login | Username `ben` / her password, inside the app itself | Already exists, nothing to do here except decide whether to keep it or reset it once it's on her machine |

The bottom two rows aren't "accounts" in the sign-up sense - just flagging them so
nothing gets missed.

**Every API-backed service moves to an account in her name - confirmed directly, not
optional.** GitHub, Gemini, and Tavily all need fresh sign-ups under her; Gmail needs a
dedicated account created for this (not her personal inbox). None of the current keys
tied to your accounts get reused - each one gets regenerated under hers and dropped
into `.env` during setup (section 4). This means quota/billing for all of it sits with
her from day one, and nothing keeps running on your accounts in the background after
handoff.

---

## 1a. Full checklist - every account, install, and download involved

Everything the project touches, in one place, so nothing gets missed during the
handoff. Ticked items are covered step-by-step later in this doc.

**Accounts to create in her name** (all required, per above):
- [ ] GitHub - github.com
- [ ] Google AI Studio (Gemini) - aistudio.google.com
- [ ] Tavily - tavily.com
- [ ] Gmail, a dedicated new address just for sending the reminder emails - not her
      personal inbox

**Software to install on her PC** (section 4 has exact commands):
- [ ] Python (same version as your machine - check with `python --version`)
- [ ] Git
- [ ] Ollama, then run `ollama pull llama3` (**~4.7GB download** - this is the actual
      model that writes every draft; the app cannot draft anything without it)
- [ ] This project's Python packages, via `pip install -r requirements.txt` - installs
      Reflex itself, the local-auth login system, `python-dotenv`, `wordfreq` (used by
      the voice-profile analysis), and `faster-whisper` (voice-note transcription)

**Downloads that happen automatically the first time, not something to run by
hand - just don't be alarmed when they happen, and make sure the PC has an internet
connection at that point:**
- [ ] The first time `reflex run` (or the `.bat` launcher) starts the app, Reflex
      downloads its own frontend build tool (`bun`) - adds a minute or two to that
      first-ever startup only.
- [ ] The first time she uploads a voice note for transcription, `faster-whisper`
      downloads the actual Whisper speech-recognition model (~150MB) from Hugging
      Face. **Known quirk from testing**: this download failed to resolve
      `huggingface.co` specifically from a Git Bash / WSL-style shell in this exact
      project's history, while it worked fine from a normal PowerShell window - if her
      first voice-note upload seems to hang or error on this step, try triggering it
      once from a plain PowerShell/cmd context, or just retry - after the first
      successful download it's cached locally and never needs the network again.
- [ ] The dashboard's fonts (Fraunces/Inter/IBM Plex Mono) load from Google Fonts in
      the browser each time - needs an internet connection to look right, but this
      isn't a one-off download, just normal page loading.

None of the "automatic" ones need her to do anything - they're listed here purely so
an unexpected pause or a first-run error doesn't look like something's broken.

---

## 2. GitHub: transfer ownership, add yourself back as a collaborator

Current repo: `https://github.com/jamesbaroniharrison-maker/WPA-Ben-Holmes-Linkedin`

**Step 1 - she creates a GitHub account** (if she doesn't have one): github.com -> Sign
up. Free tier is all that's needed here, the repo is private-eligible on free.

**Step 2 - you transfer the repo to her account:**
1. Go to the repo on GitHub -> **Settings** tab
2. Scroll to the bottom - **Danger Zone**
3. Click **Transfer ownership**
4. Type the repo name to confirm, enter her GitHub username, submit
5. She'll get an email/notification to accept the transfer - she needs to click accept
6. Once accepted, the repo now lives at `https://github.com/<her-username>/WPA-Ben-Holmes-Linkedin`

**Step 3 - add yourself as a collaborator on her (now-transferred) repo:**
1. She goes to the repo -> **Settings** -> **Collaborators**
2. **Add people** -> enter your GitHub username -> send invite
3. You accept the invite (email or github.com/notifications)
4. You now have push access to her repo, same as before, just no longer the owner

**After transfer, update your local remote** (on your own machine, if you're keeping a
working copy):
```
git remote set-url origin https://github.com/<her-username>/WPA-Ben-Holmes-Linkedin.git
```

**Alternative, if you'd rather not transfer** (e.g. you want to keep your own copy for
a portfolio): she creates a brand-new empty repo instead, and you push your existing
history into it:
```
git remote add her-repo https://github.com/<her-username>/<new-repo-name>.git
git push her-repo main
```
Then she adds you as a collaborator on her new repo (same Settings -> Collaborators
steps above). This leaves two separate repos existing in parallel rather than one
being the single source of truth - transfer is cleaner unless you specifically want
that.

---

## 3. Moving the API-key accounts to her name (required)

**Gemini**: she goes to https://aistudio.google.com, signs in with a Google account
(new or existing), clicks **Get API key** -> **Create API key**. Paste the new value
into `GEMINI_API_KEY` in `.env` on her machine.

**Tavily**: she goes to https://tavily.com, signs up free, the API key is on her
dashboard immediately. Paste into `TAVILY_API_KEY`.

**Gmail (for sending the two reminder emails)**: same recommendation as before - a
*dedicated* Gmail account for this, not her personal one. She creates it, turns on
2-Step Verification (Google Account -> Security), generates an **App Password**
(Security -> App Passwords), and that App Password (not her real Gmail password) goes
into `EMAIL_APP_PASSWORD`, with the address itself in `EMAIL_ADDRESS`.

---

## 4. Setting the app up on her PC

This is the technical part - realistically you doing this together with her (or for
her) rather than her following it solo, hence the separate simple doc for her covers
usage, not this setup.

**Prerequisites to install on her machine** (see section 1a for the full checklist -
this is the same list, with exact commands):
1. **Python** (same version you're running - `python --version` on your machine to
   check, currently 3.14.x) - python.org/downloads
2. **Git** (for `git clone` / `git pull`) - git-scm.com
3. **Ollama** - ollama.com/download, then once installed:
   ```
   ollama pull llama3
   ```
   (This is the ~4.7GB model that does all the actual drafting. Confirm it worked with
   `ollama list`. Nothing in the app will draft a single post without this step done.)

**Getting the code:**
```
git clone https://github.com/<her-username>/WPA-Ben-Holmes-Linkedin.git
cd WPA-Ben-Holmes-Linkedin
python -m venv venv
venv\Scripts\activate
cd wpa_content_engine
pip install -r requirements.txt
```
This last command also pulls in `wordfreq` (used by the voice-profile analysis) and
`faster-whisper` (voice-note transcription) - nothing further to install for either,
though `faster-whisper` will do its own one-off model download the first time she
actually uploads a voice note (see section 1a for the known quirk with that).

**Environment file:**
```
copy .env.example .env
```
Then fill in `.env` with the real values from her new accounts (section 3) -
`GEMINI_API_KEY`, `TAVILY_API_KEY`, `EMAIL_ADDRESS`, `EMAIL_APP_PASSWORD`. Leave
`OLLAMA_BASE_URL`/`OLLAMA_MODEL`/`DATABASE_URL` as the defaults already in
`.env.example` - those aren't accounts, just local config that stays the same on any
machine.

**Database:**
- **Option A - fresh start**: run `reflex db init` then `reflex db migrate` from
  inside `wpa_content_engine/` - she starts with an empty topic bank, no voice
  profile, no post history.
- **Option B - bring her existing data across (recommended)**: copy
  `wpa_content_engine\wpa_content_engine.db` from your machine straight into the same
  path on hers, *then* run `reflex db migrate` (in case her copy is one migration
  behind). This carries over her real voice profile (built from her 37 LinkedIn
  posts), any drafts/accepted/rejected posts already in the system, the topic bank,
  and her email settings. This is almost certainly what you want - rebuilding the
  voice profile from scratch would mean re-running the whole level 3 pipeline again.

**Create her dashboard login** (this is separate from all the accounts above - it's
the app's own username/password):
- If you copied the `.db` file across (Option B), her existing login already exists in
  it - nothing to do.
- If starting fresh (Option A), create it the same way it was originally done:
  ```
  python -c "
  import reflex as rx
  from reflex_local_auth import LocalUser
  with rx.session() as session:
      user = LocalUser()
      user.username = 'ben'
      user.password_hash = LocalUser.hash_password('CHOOSE_A_REAL_PASSWORD_HERE')
      user.enabled = True
      session.add(user)
      session.commit()
  "
  ```

**Register the three Windows Scheduled Tasks** (research cron + 2 email jobs) - from
an **elevated** (Run as Administrator) PowerShell prompt:
```
cd wpa_content_engine\scripts
.\register_scheduled_task.ps1
.\register_email_tasks.ps1
```

**Test it end to end:**
1. Double-click `Start WPA Content Engine.bat` in the project root
2. Confirm it opens the browser to the login page
3. Log in, confirm her existing data shows up (if Option B) - Stats should show real
   numbers, Topic Bank/Accepted/History should have real content
4. From Settings, click "Run research now" and confirm it completes without error
5. Confirm `Get-ScheduledTask -TaskName "WPA*"` shows all three as `Ready`

---

## 5. Decommissioning your copy (whenever you're ready)

Not urgent, but once she's confirmed everything works on her end:
- Unregister the three Scheduled Tasks on your machine so they stop firing from a
  now-redundant copy:
  ```
  Unregister-ScheduledTask -TaskName "WPA Daily Research Cron" -Confirm:$false
  Unregister-ScheduledTask -TaskName "WPA Weekly Reminder Email" -Confirm:$false
  Unregister-ScheduledTask -TaskName "WPA Weekly Digest Email" -Confirm:$false
  ```
- Keep your local folder around as a backup for a while rather than deleting
  immediately - cheap insurance in case anything on her side needs re-checking.

---

## 6. Going forward, as a collaborator (not owner)

Nothing changes about how you actually work day to day - `git pull`/`git push` work
exactly the same as a collaborator as they did as owner. The only things that change
are administrative: you can't change repo-level settings (visibility, deleting the
repo, transferring it again) or manage other collaborators - only she can, as owner.
For anything code-level, it's business as usual.
