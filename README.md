# learnit-study-assistant

`learnit-study-assistant` is a local-first Python command-line project for students using
ITU LearnIT/Moodle. It is inspired by `learnit-backup`.

## Current scope

This phase includes:

- A Python package under `src/learnit_study/`
- A Typer-based CLI entry point named `learnit-study`
- Cookie-based LearnIT authentication
- Current course listing
- Course page inspection
- Local material downloading
- Per-material text extraction into `extracted/`
- Per-material local note generation into `notes/`

This project does not include:

- AI note generation
- A GUI
- Video downloads
- Kaltura transcription
- A multi-user server
- A database

## CLI shape

```bash
learnit-study auth check
learnit-study courses list
learnit-study course inspect --course 3025533
learnit-study course download --course 3025533
learnit-study text extract --course 3025533
learnit-study notes generate --course 3025533 --no-ai
learnit-study flashcards generate
```

Text extraction and local notes are per material. A section folder contains `materials/`,
`extracted/`, `notes/`, and `section_manifest.json`.

## Privacy and security

This project is intended to be local-first and privacy-conscious.

- Never commit or log cookies.
- Never commit or log API keys.
- Never commit downloaded course materials.
- Never commit generated notes.
- Use `cookie.txt`, `.env`, or environment variables for secrets.
- Keep generated output under ignored folders such as `output/`, `backup/`, or `logs/`.

The LearnIT browser cookie is a live credential for your student account. Anyone with that
cookie may be able to access LearnIT as you until it expires, so keep it private and never
share it or commit it to git.

Course materials should only be sent to an AI provider if a future AI mode is explicitly
enabled by the user. AI note generation is not currently implemented.

ChatGPT Plus does not include OpenAI API usage. If future AI features use the OpenAI API,
that requires separate API billing and an API key.

## Development

Install the project in editable mode:

```bash
python -m pip install -e ".[dev]"
```

Run tests:

```bash
python -m pytest
```
