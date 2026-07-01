# learnit-study-assistant

`learnit-study-assistant` is a local-first Python command-line tool for students
using ITU LearnIT/Moodle. It logs in with your existing LearnIT browser session
cookie, lists your courses, downloads uploaded course materials, extracts text,
and generates per-material study notes.

The project is inspired by `learnit-backup`, but it uses a cleaner package
structure and a privacy-conscious local workflow.

## What It Does

Current features:

- Checks LearnIT authentication with your own browser cookie.
- Lists current/in-progress LearnIT courses by default.
- Can include old courses or StudyLab/non-course entries when requested.
- Inspects LearnIT course pages and shows sections, lectures, and activities.
- Downloads supported course materials into a local `output/` folder.
- Preserves the LearnIT section/lecture folder structure.
- Extracts text from downloaded files.
- Generates local/free deterministic notes into `notes/`.
- Optionally generates Gemini AI notes into `AI notes/` when explicitly enabled.
- Keeps downloaded files, extracted text, generated notes, cookies, and API keys
  local and git-ignored.

Not included:

- No GUI.
- No video downloading.
- No Kaltura transcription.
- No multi-user server.
- No database.
- No assignment submission scraping.
- No forum scraping.

## Install

From the project folder:

```powershell
python -m pip install -e ".[dev]"
```

Check that the CLI is available:

```powershell
learnit-study --help
```

If Windows cannot find `learnit-study`, reinstall with
`python -m pip install -e ".[dev]"` and make sure your Python Scripts directory
is on PATH.

The README examples assume the `learnit-study` console script is available.

Run tests:

```powershell
python -m pytest
```

## Privacy And Security

This project is designed to be local-first.

Never commit or log:

- LearnIT cookies
- API keys
- downloaded course materials
- extracted text
- generated notes
- logs

The `.gitignore` protects common local/private paths:

```txt
cookie.txt
.env
output/
backup/
logs/
```

### LearnIT Cookie Warning

Your LearnIT cookie is a live login credential. Anyone with that cookie may be
able to access LearnIT as you until it expires. Keep it private.

The app can load the cookie from:

1. `--cookie "..."` on the CLI
2. `cookie.txt` in the project folder
3. `LEARNIT_COOKIE` environment variable

The app should never print the full cookie.

### AI Privacy Warning

Course material is only sent to an AI provider when you explicitly use `--ai`.
Local note generation with `--no-ai` does not call an AI API.

Gemini AI mode sends extracted markdown text from `extracted/*.md`, not the
original downloaded files. Set `GEMINI_API_KEY` in your environment to use
Gemini.

ChatGPT Plus does not include OpenAI API usage. If future OpenAI features are
added, they would require separate API billing and an API key.

## Recommended Workflow

Use this sequence for a course:

```powershell
learnit-study auth check
learnit-study courses list
learnit-study course inspect --course 3025533
learnit-study course download --course 3025533
learnit-study text extract --course 3025533
learnit-study notes generate --course 3025533 --no-ai
```

Optional Gemini AI workflow:

```powershell
learnit-study notes estimate-cost --course 3025533 --detail-level exam
learnit-study notes generate --course 3025533 --ai --max-materials 1
learnit-study notes generate --course 3025533 --ai --requests-per-minute 10
```

Use `--max-materials 1` first as a small real-world test before generating AI
notes for a full course.

## Web MVP

The project also includes a small FastAPI web MVP around the existing CLI/core
logic. It is intended for a single-user personal deployment, for example on
Render. The CLI remains fully supported.

The web app reuses the same backend modules as the CLI:

- `auth`
- `courses`
- `parser`
- `downloader`
- `extraction`
- `notes`
- `ai_notes`

It does not add user accounts, a database, payments, background queues, public
sharing, or a React frontend.

### Run Locally

Install dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Run the web app:

```powershell
uvicorn learnit_study.web.app:app --reload
```

Open:

```txt
http://127.0.0.1:8000
```

The web app defaults to `output/` locally. Override it with:

```powershell
$env:LEARNIT_OUTPUT_DIR = "output"
```

For Gemini AI notes, set:

```powershell
$env:GEMINI_API_KEY = "your-api-key"
```

Local password protection is optional. If you want to test the login flow:

```powershell
$env:LEARNIT_WEB_PASSWORD = "choose-a-local-password"
$env:LEARNIT_WEB_SECRET_KEY = "choose-a-long-random-local-secret"
uvicorn learnit_study.web.app:app --reload
```

If `LEARNIT_WEB_PASSWORD` is not set, local development runs without login.

### Web Routes

| Route | Method | Purpose |
| --- | --- | --- |
| `/login` | `GET` | Shows the single-user login form when password protection is enabled. |
| `/login` | `POST` | Checks `LEARNIT_WEB_PASSWORD` and stores only an authenticated boolean in the session. |
| `/logout` | `POST` | Clears the web session. |
| `/` | `GET` | Home page, privacy warning, LearnIT cookie form. |
| `/auth/check` | `POST` | Checks the pasted LearnIT cookie. The cookie is not shown back to the user. |
| `/courses` | `GET` | Lists current courses using the active temporary web session. |
| `/course/{course_id}` | `GET` | Shows course actions. |
| `/course/{course_id}/inspect` | `POST` | Starts an inspect job. |
| `/course/{course_id}/download` | `POST` | Starts a download job. |
| `/course/{course_id}/extract` | `POST` | Starts a text extraction job. |
| `/course/{course_id}/notes/local` | `POST` | Starts local note generation. |
| `/course/{course_id}/notes/ai/estimate` | `POST` | Shows Gemini cost estimate. |
| `/course/{course_id}/notes/ai/generate` | `POST` | Starts Gemini AI note generation. |
| `/jobs/{job_id}` | `GET` | Shows in-memory job status and summary. |
| `/course/{course_id}/notes` | `GET` | Lists and displays generated local/AI notes as escaped text. |

### Web Cookie Behavior

If `LEARNIT_WEB_PASSWORD` is set, all app pages except `/login` and static
assets require login. Static CSS remains public. Login success stores only a
boolean in the signed session, never the password.

For the MVP, the user pastes a LearnIT browser cookie into the web form. The
server stores it only in an in-memory dictionary keyed by a temporary browser
session cookie. This avoids writing the LearnIT cookie to disk, manifests, or
the repo.

Important limitations:

- In-memory cookies disappear when the server restarts.
- This is not a production multi-user authentication system.
- Only use your own LearnIT account/session.
- Do not deploy this as an open public SaaS.

### Web Jobs

Long actions run through a simple in-memory thread job runner:

- course inspection
- downloads
- text extraction
- local note generation
- Gemini AI note generation

The job page shows status, summary counts, result text, and failures.

Important limitations:

- Jobs disappear when the server restarts.
- Render free instances can restart or sleep.
- This MVP does not use Celery, Redis, or a database.
- Local files on Render free services may disappear after restart unless you
  configure persistent storage.

### Render Deployment

This repo includes `render.yaml`.

Suggested Render settings:

```yaml
services:
  - type: web
    name: learnit-study
    env: python
    buildCommand: pip install -e ".[dev]"
    startCommand: uvicorn learnit_study.web.app:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: GEMINI_API_KEY
        sync: false
      - key: LEARNIT_OUTPUT_DIR
        value: /tmp/learnit-output
      - key: LEARNIT_WEB_PASSWORD
        sync: false
      - key: LEARNIT_WEB_SECRET_KEY
        sync: false
```

Render environment variables:

| Variable | Required | Description |
| --- | --- | --- |
| `GEMINI_API_KEY` | Only for AI notes | Server-side Gemini API key. Configure it in the Render dashboard. Do not enter it in the web UI. |
| `LEARNIT_OUTPUT_DIR` | Recommended on Render | Use `/tmp/learnit-output` unless you configure persistent storage. |
| `LEARNIT_WEB_PASSWORD` | Yes for Render | Single-user password required before anyone can use the web app. Use a strong unique password. |
| `LEARNIT_WEB_SECRET_KEY` | Yes for Render | Long random secret used to sign browser sessions. Do not reuse the web password. |
| `LEARNIT_WEB_WORKERS` | No | Number of in-memory worker threads. Default: `2`. |

Render notes:

- The service must bind to `0.0.0.0`.
- Render provides `$PORT`; the start command uses it.
- Set `LEARNIT_WEB_PASSWORD` before exposing the service. Without it, the web
  app is open to anyone who can reach the URL.
- Set `LEARNIT_WEB_SECRET_KEY` to a long random value. If password protection is
  enabled on Render and the secret is missing, startup fails clearly.
- `/tmp/learnit-output` is suitable for the MVP but is not durable permanent
  storage.
- Add a persistent disk later if you want files to survive restarts.

### Safe And Unsafe In The Web MVP

Safer:

- Uses existing tested core logic.
- Does not write LearnIT cookies to output manifests.
- Does not ask for Gemini API keys in the browser.
- Supports single-user password protection with `LEARNIT_WEB_PASSWORD`.
- Shows notes as escaped text instead of unsafe rendered HTML.
- Keeps local notes and AI notes in separate folders.

Unsafe or not production-ready:

- No user accounts.
- No database.
- No durable job queue.
- In-memory sessions and jobs vanish on restart.
- Pasted LearnIT cookies are live credentials.
- Password protection is simple single-user protection, not a complete identity
  or authorization system.
- A public deployment should be treated as a personal/single-user app only.
- Downloaded course materials may exist on the server filesystem while the app
  is running.

## Output Folder Structure

Downloaded and generated files are saved under `output/` by default.

Example:

```txt
output/
  3025533 - Database and Information Systems Foundations (Spring 2026)/
    manifest.json
    Lecture 2 Information Systems in Global Business Today/
      materials/
        Lecture 2.pdf
        Reading Chapter 2.pdf
      extracted/
        Lecture 2.md
        Reading Chapter 2.md
      notes/
        Lecture 2.notes.md
        Reading Chapter 2.notes.md
      AI notes/
        Lecture 2.ai-notes.md
        Reading Chapter 2.ai-notes.md
      section_manifest.json
```

Folder meanings:

- `materials/`: original downloaded files.
- `extracted/`: per-material extracted markdown text.
- `notes/`: local/free deterministic per-material notes from `--no-ai`.
- `AI notes/`: Gemini per-material AI notes from `--ai`.
- `section_manifest.json`: per-section extraction, note, and failure metadata.
- `manifest.json`: course-level download/extraction/note summary.

The app no longer creates combined section-level `extracted_text.md` or
`notes.md` files. Each material gets its own extracted text file and notes file.

## Command Reference

Use `learnit-study --help` for a short overview and
`learnit-study <command> --help` for detailed CLI help.

All commands support `-h` as an alias for `--help`.

## `learnit-study auth check`

Checks whether a LearnIT cookie is available and valid. It fetches
`https://learnit.itu.dk/my/` and verifies that Moodle returns a `sesskey`.

Usage:

```powershell
learnit-study auth check
learnit-study auth check --cookie "MoodleSession=..."
```

Flags:

| Flag | Required | Description |
| --- | --- | --- |
| `--cookie TEXT` | No | LearnIT browser Cookie header value. Prefer `cookie.txt` or `LEARNIT_COOKIE` so the cookie is not visible in shell history. |
| `-h`, `--help` | No | Show command help. |

Cookie lookup order:

1. `--cookie`
2. `cookie.txt`
3. `LEARNIT_COOKIE`

Example `cookie.txt`:

```txt
MoodleSession=your-session-cookie-value; another_cookie=value
```

Do not commit `cookie.txt`.

## `learnit-study courses list`

Lists LearnIT courses using the authenticated session.

Default behavior:

- Uses Moodle classification `inprogress`.
- Shows current/in-progress courses.
- Hides StudyLab/non-course entries.

Usage:

```powershell
learnit-study courses list
learnit-study courses list --all
learnit-study courses list --classification past
learnit-study courses list --include-non-courses
learnit-study courses list --all --include-non-courses
```

Flags:

| Flag | Required | Description |
| --- | --- | --- |
| `--cookie TEXT` | No | LearnIT browser Cookie header value. Prefer `cookie.txt` or `LEARNIT_COOKIE`. |
| `--all` | No | Show all enrolled courses, including old courses. Equivalent to classification `all`. |
| `--classification inprogress\|all\|past\|future` | No | Advanced Moodle timeline classification. Default is `inprogress`. |
| `--include-non-courses` | No | Include StudyLab/non-course entries. Hidden by default. |
| `-h`, `--help` | No | Show command help. |

Notes:

- Use either `--all` or `--classification`, not both.
- StudyLab filtering is case-insensitive and checks `studylab`, `study lab`,
  and `study-lab` in course names.

Examples:

```powershell
# Current real courses only
learnit-study courses list

# All real courses, excluding StudyLab
learnit-study courses list --all

# Past real courses
learnit-study courses list --classification past

# Current courses plus StudyLab/non-course entries
learnit-study courses list --include-non-courses
```

## `learnit-study course inspect`

Fetches a LearnIT course page and prints the parsed section/lecture/activity
structure without downloading files.

Usage:

```powershell
learnit-study course inspect --course 3025533
learnit-study course inspect --course 3025533 --cookie "MoodleSession=..."
```

Flags:

| Flag | Required | Description |
| --- | --- | --- |
| `--course TEXT` | Yes | LearnIT course ID. |
| `--cookie TEXT` | No | LearnIT browser Cookie header value. Prefer `cookie.txt` or `LEARNIT_COOKIE`. |
| `-h`, `--help` | No | Show command help. |

Use this command before downloading to confirm that the parser groups materials
under the expected LearnIT lecture/section headings.

Example:

```powershell
learnit-study course inspect --course 3025533
```

Output includes section names, activity names, activity types, and Moodle `cmid`
values.

## `learnit-study course download`

Downloads supported materials from a LearnIT course into a local course folder.

Usage:

```powershell
learnit-study course download --course 3025533
learnit-study course download --course 3025533 --out output
learnit-study course download --course 3025533 --delay 0.5
learnit-study course download --course 3025533 --cookie "MoodleSession=..."
```

Flags:

| Flag | Required | Description |
| --- | --- | --- |
| `--course TEXT` | Yes | LearnIT course ID. |
| `--out TEXT` | No | Output directory for downloaded materials. Default: `output`. |
| `--delay FLOAT` | No | Delay in seconds between activities. Default: `0.0`. Useful if you want to be gentler on LearnIT. |
| `--cookie TEXT` | No | LearnIT browser Cookie header value. Prefer `cookie.txt` or `LEARNIT_COOKIE`. |
| `-h`, `--help` | No | Show command help. |

Supported activity types include Moodle resources/files, folders, pages, and
URLs/links. Unsupported activities are skipped and recorded in manifests.

Download behavior:

- Creates a course folder named `<course_id> - <course title>`.
- Creates one folder per LearnIT section/lecture.
- Saves original files under `materials/`.
- Records links in `links.md` where relevant.
- Writes `section_manifest.json` per section.
- Writes course-level `manifest.json`.
- Skips existing non-empty files.
- Uses `.part` files while downloading and renames after success.
- Removes incomplete `.part` files when possible if a download fails.
- Shortens long Windows paths while preserving readable names and file
  extensions.

Example:

```powershell
learnit-study course download --course 3025533 --out output --delay 0.25
```

## `learnit-study text extract`

Extracts readable text from already-downloaded local files. This command does
not require LearnIT authentication and does not make network requests.

Usage:

```powershell
learnit-study text extract --course 3025533
learnit-study text extract --course 3025533 --out output
learnit-study text extract --course-dir "output/3025533 - Database and Information Systems Foundations (Spring 2026)"
```

Flags:

| Flag | Required | Description |
| --- | --- | --- |
| `--course TEXT` | Use `--course` or `--course-dir` | LearnIT course ID. The app finds a matching folder like `<course_id> - *` under `--out`. |
| `--out TEXT` | No | Output directory containing downloaded courses. Default: `output`. |
| `--course-dir TEXT` | Use `--course` or `--course-dir` | Exact downloaded course folder. Use this if the app cannot uniquely find the course folder. |
| `-h`, `--help` | No | Show command help. |

Supported file types:

- `.pdf` using `pypdf`
- `.docx` using `python-docx`
- `.pptx` using `python-pptx`
- `.html` / `.htm`
- `.txt`
- `.md`
- `.csv`
- `.sql`
- `.py`
- `.json`
- `.xml`
- `.yaml`
- `.yml`

Unsupported files are skipped safely and recorded in `section_manifest.json`.

Extraction output:

```txt
<section>/
  extracted/
    <safe material name>.md
```

Each extracted markdown file includes:

- source filename
- original material relative path
- extracted text

Example:

```powershell
learnit-study text extract --course 3025533
```

## `learnit-study notes generate`

Generates study notes from per-material extracted markdown files.

Default mode is local/free deterministic notes:

```powershell
learnit-study notes generate --course 3025533
learnit-study notes generate --course 3025533 --no-ai
```

Gemini AI mode is only used when `--ai` is passed:

```powershell
learnit-study notes generate --course 3025533 --ai
```

Flags:

| Flag | Required | Description |
| --- | --- | --- |
| `--course TEXT` | Use `--course` or `--course-dir` | LearnIT course ID. The app finds a matching folder like `<course_id> - *` under `--out`. |
| `--out TEXT` | No | Output directory containing downloaded courses. Default: `output`. |
| `--course-dir TEXT` | Use `--course` or `--course-dir` | Exact downloaded course folder. |
| `--no-ai` | No | Use local non-AI note generation. This is the default mode. |
| `--ai` | No | Enable explicit Gemini AI mode. Sends extracted text to Gemini after confirmation. |
| `--provider TEXT` | No | AI provider. Currently only `gemini`. Default: `gemini`. |
| `--model TEXT` | No | Gemini model to use. Supported: `gemini-3.1-flash-lite`, `gemini-3.5-flash`. Default: `gemini-3.1-flash-lite`. |
| `--detail-level TEXT` | No | AI note depth. Use `exam` for detailed exam-prep notes or `standard` for shorter notes. Default: `exam`. |
| `--max-materials INTEGER` | No | Limit AI generation to the first N new extracted materials. Useful for testing cost and quality. |
| `--requests-per-minute INTEGER` | No | Throttle Gemini API calls. Default: `10`. Useful for Gemini free-tier rate limits. |
| `--retry-attempts INTEGER` | No | Maximum attempts for rate-limited Gemini requests. Default: `3`. |
| `--retry-base-delay FLOAT` | No | Base delay in seconds for exponential rate-limit backoff. Default: `10.0`. |
| `--overwrite` | No | Regenerate existing non-empty AI note files. Without this, existing AI notes are skipped. |
| `--yes` | No | Skip the AI privacy/cost confirmation prompt. Only use this when you already understand what will be sent. |
| `-h`, `--help` | No | Show command help. |

Local note behavior:

- Reads files from `extracted/`.
- Writes notes to `notes/<material>.notes.md`.
- Does not call any AI API.
- Does not require `GEMINI_API_KEY`.

AI note behavior:

- Reads files from `extracted/`.
- Shows a cost estimate and privacy warning before API calls.
- Requires `GEMINI_API_KEY`.
- Writes notes to `AI notes/<material>.ai-notes.md`.
- Skips existing non-empty AI notes by default.
- Uses `--overwrite` to regenerate existing AI notes.
- Uses rate limiting and retry/backoff for Gemini quota errors.

Set Gemini API key:

```powershell
$env:GEMINI_API_KEY = "your-api-key"
```

Local examples:

```powershell
# Generate local/free notes for all extracted materials
learnit-study notes generate --course 3025533

# Same as above, explicitly local
learnit-study notes generate --course 3025533 --no-ai

# Use an exact course folder
learnit-study notes generate --course-dir "output/3025533 - Database and Information Systems Foundations (Spring 2026)"
```

AI examples:

```powershell
# Safe first test: generate one AI note
learnit-study notes generate --course 3025533 --ai --max-materials 1

# Detailed exam-focused notes, conservative free-tier rate limit
learnit-study notes generate --course 3025533 --ai --detail-level exam --requests-per-minute 10

# Shorter AI notes
learnit-study notes generate --course 3025533 --ai --detail-level standard --max-materials 1

# Use a specific model
learnit-study notes generate --course 3025533 --ai --provider gemini --model gemini-3.1-flash-lite

# Resume safely after rate limits or interruption
learnit-study notes generate --course 3025533 --ai --requests-per-minute 10

# Regenerate existing AI notes
learnit-study notes generate --course 3025533 --ai --overwrite --max-materials 1

# Non-interactive run after you already reviewed the warning
learnit-study notes generate --course 3025533 --ai --yes --requests-per-minute 10
```

Recommended Gemini free-tier settings:

```powershell
learnit-study notes generate --course 3025533 --ai --requests-per-minute 10 --retry-attempts 3 --retry-base-delay 10
```

## `learnit-study notes estimate-cost`

Estimates Gemini AI note generation cost without making API calls. This command
does not require `GEMINI_API_KEY`.

Usage:

```powershell
learnit-study notes estimate-cost --course 3025533
learnit-study notes estimate-cost --course 3025533 --detail-level exam
learnit-study notes estimate-cost --course 3025533 --provider gemini --model gemini-3.1-flash-lite
learnit-study notes estimate-cost --course-dir "output/3025533 - Database and Information Systems Foundations (Spring 2026)"
```

Flags:

| Flag | Required | Description |
| --- | --- | --- |
| `--course TEXT` | Use `--course` or `--course-dir` | LearnIT course ID. The app finds a matching folder like `<course_id> - *` under `--out`. |
| `--out TEXT` | No | Output directory containing downloaded courses. Default: `output`. |
| `--course-dir TEXT` | Use `--course` or `--course-dir` | Exact downloaded course folder. |
| `--provider TEXT` | No | AI provider. Currently only `gemini`. Default: `gemini`. |
| `--model TEXT` | No | Gemini model to estimate. Supported: `gemini-3.1-flash-lite`, `gemini-3.5-flash`. |
| `--detail-level TEXT` | No | `exam` estimates longer detailed notes. `standard` estimates shorter notes. Default: `exam`. |
| `--max-materials INTEGER` | No | Estimate only the first N new extracted materials. |
| `-h`, `--help` | No | Show command help. |

Detail levels:

- `exam`: detailed exam-preparation notes. Output token estimate is higher.
- `standard`: shorter AI notes. Output token estimate is lower.

Example:

```powershell
learnit-study notes estimate-cost --course 3025533 --detail-level exam --max-materials 5
```

## `learnit-study flashcards generate`

Placeholder for future flashcard generation. It exists in the CLI, but real
flashcard generation is not implemented yet.

Usage:

```powershell
learnit-study flashcards generate --course 3025533
```

Flags:

| Flag | Required | Description |
| --- | --- | --- |
| `--course TEXT` | Yes | LearnIT course ID. |
| `-h`, `--help` | No | Show command help. |

## Common Recipes

### Start From Scratch

```powershell
learnit-study auth check
learnit-study courses list
learnit-study course inspect --course 3025533
learnit-study course download --course 3025533
learnit-study text extract --course 3025533
learnit-study notes generate --course 3025533 --no-ai
```

### Download To A Custom Folder

```powershell
learnit-study course download --course 3025533 --out backup
learnit-study text extract --course 3025533 --out backup
learnit-study notes generate --course 3025533 --out backup --no-ai
```

### Use Exact Course Directory

```powershell
learnit-study text extract --course-dir "output/3025533 - Database and Information Systems Foundations (Spring 2026)"
learnit-study notes generate --course-dir "output/3025533 - Database and Information Systems Foundations (Spring 2026)" --no-ai
```

### Resume Gemini AI Generation Safely

Existing non-empty AI notes are skipped by default, so rerunning the command is
safe:

```powershell
learnit-study notes generate --course 3025533 --ai --requests-per-minute 10
```

### Regenerate One AI Note For Testing

```powershell
learnit-study notes generate --course 3025533 --ai --overwrite --max-materials 1 --requests-per-minute 10
```

## Troubleshooting

### `Missing LearnIT cookie`

Provide a cookie using one of:

```powershell
learnit-study auth check --cookie "MoodleSession=..."
```

```powershell
$env:LEARNIT_COOKIE = "MoodleSession=..."
learnit-study auth check
```

or create `cookie.txt` in the project folder.

### `cookie may be missing, wrong, or expired`

Your browser session may have expired. Log into LearnIT in your browser again,
copy a fresh cookie, and rerun:

```powershell
learnit-study auth check
```

### Course Folder Not Found

If extraction or notes cannot find a folder by course ID, use `--course-dir`:

```powershell
learnit-study text extract --course-dir "output/3025533 - Database and Information Systems Foundations (Spring 2026)"
```

### Gemini Rate Limits

If Gemini returns quota or rate-limit errors, lower the request rate and rerun.
Existing AI notes are skipped by default.

```powershell
learnit-study notes generate --course 3025533 --ai --requests-per-minute 5 --retry-attempts 5 --retry-base-delay 20
```

### Old AI Notes In `notes/`

Earlier development builds may have written AI notes into `notes/`. New AI notes
are written only to `AI notes/`. Regenerate if you want the separated layout:

```powershell
learnit-study notes generate --course 3025533 --ai --overwrite
```

## Development

Install in editable mode:

```powershell
python -m pip install -e ".[dev]"
```

Run tests:

```powershell
python -m pytest
```

Run a compile check:

```powershell
python -m compileall src tests
```
