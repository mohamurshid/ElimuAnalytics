"""
What each question status permits, in one place.

Agreed 20 October. Every query that serves, counts or accepts answers to a
question asks this module, so the rules cannot drift apart between the quiz
endpoint, calibration and answer submission.

    status     served in new quizzes   counts toward levels   answers accepted
    draft      no                      no                     no
    approved   yes                     yes                    yes
    reported   no                      no                     yes
    rejected   no                      no                     no
    retired    no                      no                     no

**Reported** questions stop counting until a head teacher reviews them,
because a reported question may have a wrong key and should not push a
learner onto the support list in the meantime. Their answers are kept, and
count again if the question is approved. Answers to one ARE still accepted:
a quiz loaded before the report must not be thrown away when it is
submitted.

**Rejected** drafts are kept rather than deleted, because how often teachers
approve what the AI writes is a measurement the write-up needs.
"""

from __future__ import annotations

DRAFT = "draft"
APPROVED = "approved"
REPORTED = "reported"
REJECTED = "rejected"
RETIRED = "retired"
STATUSES = (DRAFT, APPROVED, REPORTED, REJECTED, RETIRED)

SERVED = (APPROVED,)
MEASURED = (APPROVED,)
ANSWERABLE = (APPROVED, REPORTED)

TEACHER = "teacher"
AI = "ai"

MIN_OPTIONS = 2
MAX_OPTIONS = 6


def mcq_problems(
    options: list[str] | None,
    correct_option: int | None,
    misconceptions: list[str | None] | None = None,
) -> list[str]:
    """Why a multiple-choice question is malformed, or [] if it is not.

    Options and key come together or not at all: a text-only question is a
    valid question for a teacher to mark on paper, but a question with
    options and no key cannot be marked by anyone.
    """
    if options is None and correct_option is None:
        if misconceptions is not None:
            return ["misconceptions need options to belong to"]
        return []
    if options is None or correct_option is None:
        return ["options and the correct option must be given together"]

    problems: list[str] = []
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        problems.append(f"a question needs {MIN_OPTIONS} to {MAX_OPTIONS} options")
    cleaned = [o.strip() for o in options]
    if any(not o for o in cleaned):
        problems.append("an option is empty")
    if len({o.casefold() for o in cleaned}) != len(cleaned):
        problems.append("two options are the same")
    if not 0 <= correct_option < len(options):
        problems.append("the correct option is not one of the options")
    if misconceptions is not None:
        if len(misconceptions) != len(options):
            problems.append("there must be one misconception entry per option")
        elif 0 <= correct_option < len(options) and misconceptions[correct_option]:
            problems.append("the correct option cannot carry a misconception")
    return problems
