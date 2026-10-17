"""
Generate one real report, end to end, against the running backend.

    tasks run                   (in one terminal)
    python spike\\first_report.py   (in another, venv active)

This is the first live API call in the project. Everything up to here was
tested against a stubbed generator, which is deliberate - a test that calls an
API fails for reasons unrelated to the code - but a stub cannot tell you
whether the real model cites the real curriculum. This can.

It exists as a script rather than a sequence of curl commands because doing it
by hand means copying a JWT and two UUIDs between four requests, and because
the figures it prints - verdict, exportability, tokens, thinking share, cost -
are the ones Chapter 5 needs. Re-running it is how those figures get refreshed.

The server needs ANTHROPIC_API_KEY in its environment, not this script's: the
model is called server-side.

    python spike/first_report.py
    python spike/first_report.py --learner Amina --json
"""

from __future__ import annotations

import argparse
import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"
EMAIL = "head@example.school"
PASSWORD = "elimu-demo"


def die(message: str, response: httpx.Response | None = None) -> None:
    print(f"\nFAILED: {message}")
    if response is not None:
        print(f"  HTTP {response.status_code}")
        try:
            print(f"  {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        except ValueError:
            print(f"  {response.text[:500]}")
    sys.exit(1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--email", default=EMAIL)
    ap.add_argument("--password", default=PASSWORD)
    ap.add_argument("--learner", default="Chebet", help="match on the start of the name")
    ap.add_argument("--strand", default=None, help="match on part of the strand name")
    ap.add_argument("--json", action="store_true", help="print the raw response too")
    args = ap.parse_args()

    # A report means two model calls with adaptive thinking, so the default
    # five-second timeout is nowhere near enough.
    client = httpx.Client(base_url=args.base, timeout=180.0)

    print(f"backend: {args.base}")
    try:
        login = client.post(
            "/api/auth/login", json={"email": args.email, "password": args.password}
        )
    except httpx.ConnectError:
        die(f"nothing is listening on {args.base}. Start it with `tasks run`.")
        return
    if login.status_code != 200:
        die("login rejected", login)
    token = login.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    print(f"signed in as {login.json()['name']} ({login.json()['role']})")

    strands = client.get("/api/strands", headers=auth)
    if strands.status_code != 200:
        die("could not list strands", strands)
    rows = strands.json()
    if args.strand:
        rows = [r for r in rows if args.strand.lower() in r["name"].lower()]
    if not rows:
        die(f"no strand matching {args.strand!r}")
    strand = rows[0]
    print(f"strand:  {strand['name']}  ({strand['active_items']} active items)")

    classrooms = client.get("/api/classrooms", headers=auth)
    if classrooms.status_code != 200:
        die("could not list classrooms", classrooms)
    if not classrooms.json():
        die("no classrooms. Run `tasks seed --reset`.")
    classroom = classrooms.json()[0]
    print(f"class:   {classroom['grade']} {classroom['name']}")

    roll = client.get(f"/api/classrooms/{classroom['class_id']}/students", headers=auth)
    if roll.status_code != 200:
        die("could not list learners", roll)
    matches = [s for s in roll.json() if s["name"].startswith(args.learner)]
    if not matches:
        die(f"no learner whose name starts with {args.learner!r}")
    learner = matches[0]
    print(f"learner: {learner['name']}  ({learner['response_count']} responses)")

    print("\ngenerating (two model calls, English and Kiswahili)...")
    created = client.post(
        f"/api/students/{learner['student_id']}/reports",
        params={"strand_id": strand["strand_id"]},
        headers=auth,
    )
    if created.status_code != 201:
        die("report generation refused", created)
    report = created.json()

    rule = "=" * 74
    print(f"\n{rule}\nENGLISH\n{rule}")
    print(report["content_en"] or "(empty)")
    print(f"\n{rule}\nKISWAHILI\n{rule}")
    print(report["content_sw"] or "(empty)")

    print(f"\n{rule}\nGROUNDING\n{rule}")
    print(f"verdict:     {report['verdict']}")
    print(f"exportable:  {report['exportable']}")
    print(f"detail:      {report['detail']}")
    for language, check in (report["grounding"] or {}).items():
        print(f"\n  {language}")
        print(f"    verified citations:  {check['verbatim_quotes_verified'] or 'none'}")
        print(f"    FABRICATED:          {check['verbatim_quotes_fabricated'] or 'none'}")
        print(f"    vague (EN):          {check['vague_phrases_en'] or 'none'}")
        print(f"    vague (SW):          {check['vague_phrases_sw'] or 'none'}")
        print(f"    lexical overlap:     {check['lexical_overlap']}")
        print(f"    words:               {check['words']}")

    print(f"\n{rule}\nCOST AND PROVENANCE\n{rule}")
    print(f"model:            {report['model']}  (effort {report['effort']})")
    print(f"top similarity:   {report['top_similarity']}")
    print(f"chunk source rows:{report['chunk_source_rows']}")
    tokens_in = report["input_tokens"] or 0
    tokens_out = report["output_tokens"] or 0
    thinking = report["thinking_tokens"] or 0
    print(f"tokens:           {tokens_in} in / {tokens_out} out, both languages")
    if tokens_out:
        print(f"thinking:         {thinking} ({thinking / tokens_out * 100:.0f}% of output)")
    cost = report["cost_usd"] or 0.0
    print(f"cost:             ${cost:.6f} = {cost * 100:.3f} cents for the pair")
    print(f"60 UAT reports:   ${cost * 60:.2f}")
    print(f"\nreport_id: {report['report_id']}")

    if args.json:
        print(f"\n{rule}\nRAW\n{rule}")
        print(json.dumps(report, indent=2, ensure_ascii=False))

    print(
        "\nRead the Kiswahili as a Kiswahili speaker, not as a score: is the "
        "phrasing about the child respectful, are the technical terms the ones a "
        "Kenyan teacher uses, is it fit to send home?"
    )


if __name__ == "__main__":
    main()
