# LearnIT Study Assistant

## Goal
Build a local-first Python tool that logs into LearnIT using the student's own browser session cookie, lists their current courses, downloads uploaded course material, groups it by LearnIT section/week, extracts text from the material, and generates study notes for each lecture/section.

## Reference repo
Use https://github.com/alexop1000/learnit-backup as inspiration/reference only.

Useful reference behavior:
- load LearnIT cookie from CLI argument, cookie.txt, or LEARNIT_COOKIE
- authenticate with requests.Session
- extract Moodle sesskey from https://learnit.itu.dk/my/
- list enrolled courses through Moodle AJAX
- parse course activities and preserve section/week names
- download Moodle resources, folders, pages, and URLs

Do not copy the project blindly. Build a cleaner package structure.

## Privacy rules
- The app must run locally.
- Never commit cookies, API keys, downloaded course files, generated notes, or logs.
- Use cookie.txt, .env, or environment variables for secrets.
- Add .gitignore entries for:
  - cookie.txt
  - .env
  - output/
  - backup/
  - logs/
- Never print the full cookie.
- Never log cookies or API keys.
- Never send course material to an AI provider unless the user explicitly enables AI mode.
- Include a README warning that the cookie is a live login credential.
- AI note generation requires an OpenAI API key. ChatGPT Plus does not include API usage.

## MVP
The first version should support:
1. Loading a LearnIT cookie.
2. Authenticating to LearnIT.
3. Listing current courses.
4. Selecting one course by course ID.
5. Parsing course sections/weeks.
6. Downloading materials from resources, folders, and pages.
7. Extracting text from PDF, DOCX, PPTX, HTML, TXT, and Markdown.
8. Generating one notes.md file per section.
9. Saving everything locally.

## Not in MVP
- No GUI.
- No video downloading.
- No Kaltura transcription.
- No mobile app.
- No multi-user server.
- No database unless necessary.
- No assignment submission scraping in the first version.
- No forum scraping in the first version.

## CLI examples
```bash
learnit-study auth check
learnit-study courses list
learnit-study course download --course 3022795
learnit-study notes generate --course 3022795 --no-ai
learnit-study notes generate --course 3022795 --ai