from __future__ import annotations


def generate(course_id: str, *, ai: bool = False, no_ai: bool = False) -> str:
    mode = "ai" if ai else "local-only"
    if no_ai:
        mode = "local-only"
    return f"Placeholder: note generation is not implemented yet for course {course_id} ({mode})."
