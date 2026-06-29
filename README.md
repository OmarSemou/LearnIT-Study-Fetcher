# learnit-study-assistant

`learnit-study-assistant` is a local-first Python command-line project for students using
ITU LearnIT/Moodle. It is inspired by `learnit-backup`, but the first phase only creates
the project skeleton and CLI shape.

## Phase 1 scope

This phase includes:

- A Python package under `src/learnit_study/`
- A Typer-based CLI entry point named `learnit-study`
- Placeholder modules for authentication, courses, parsing, downloading, storage, notes,
  flashcards, and text extractors
- Basic tests that confirm the CLI loads

This phase does not include:

- Real LearnIT scraping
- AI note generation
- A GUI
- Video downloads
- Kaltura transcription
- A multi-user server
- A database

## Planned CLI shape

```bash
learnit-study auth check
learnit-study courses list
learnit-study course download
learnit-study notes generate
learnit-study flashcards generate
```

The commands currently print placeholder messages only.

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
enabled by the user. AI is not implemented in Phase 1.

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
