#!/usr/bin/env python3
"""TOEFL Reading set generator.

Generates TOEFL iBT Reading practice sets — an academic passage plus a batch of
questions in the official question-type mix — using the Claude API.

Usage examples:
    # One medium set, model picks the topic, write JSON + HTML to ./output
    python toefl_set_generator.py

    # Three hard sets about astronomy, 12 questions each, JSON only
    python toefl_set_generator.py --count 3 --difficulty hard \
        --topic "the formation of galaxies" --num-questions 12 --format json

    # A single easy set, print the human-readable version to the terminal too
    python toefl_set_generator.py --difficulty easy --print

Requires the ANTHROPIC_API_KEY environment variable.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import re
import sys
from pathlib import Path

try:
    import anthropic
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - dependency guard
    sys.stderr.write(
        "Missing dependency: %s\n"
        "Install requirements first:  pip install -r requirements.txt\n" % exc.name
    )
    raise SystemExit(1)


# The model is fixed to the most capable current Claude model. Override with
# --model only if you have a specific reason.
DEFAULT_MODEL = "claude-opus-4-8"

# The official TOEFL iBT Reading question types. The generator is told to draw
# from this set so each passage exercises a realistic mix.
QUESTION_TYPES = [
    "Factual Information",
    "Negative Factual Information",
    "Inference",
    "Rhetorical Purpose",
    "Vocabulary",
    "Reference",
    "Sentence Simplification",
    "Insert Text",
    "Prose Summary",
]

DIFFICULTY_GUIDANCE = {
    "easy": (
        "Aim for the lower end of TOEFL difficulty: a ~500-word passage, "
        "concrete vocabulary, and questions that mostly test directly stated "
        "information."
    ),
    "medium": (
        "Aim for a typical TOEFL difficulty: a ~650-word passage with some "
        "abstract argumentation and a balanced mix of literal and inferential "
        "questions."
    ),
    "hard": (
        "Aim for the upper end of TOEFL difficulty: a ~750-word passage with "
        "dense academic argumentation, low-frequency vocabulary, and a higher "
        "proportion of inference, rhetorical-purpose, and sentence-"
        "simplification questions."
    ),
}


class Question(BaseModel):
    """A single Reading question.

    `options` holds the answer choices in order (4 for standard questions, 6
    for a Prose Summary). `correct_letters` holds the letter(s) of the correct
    choice(s) — a single letter for standard questions, three for a Prose
    Summary worth two points.
    """

    number: int = Field(description="1-based position of this question in the set")
    question_type: str = Field(
        description="One of the official TOEFL Reading question types"
    )
    prompt: str = Field(description="The question stem shown to the test taker")
    options: list[str] = Field(
        description="Answer choices in order; 4 for standard questions, 6 for Prose Summary"
    )
    correct_letters: list[str] = Field(
        description="Letter(s) of the correct choice(s), e.g. ['B'] or ['A','C','E']"
    )
    explanation: str = Field(
        description="A brief rationale for the answer, citing the passage"
    )


class ReadingSet(BaseModel):
    """A complete TOEFL Reading practice set."""

    title: str = Field(description="A short academic title for the passage")
    topic: str = Field(description="The subject area, e.g. 'marine biology'")
    passage: str = Field(
        description=(
            "The reading passage. Paragraphs separated by blank lines. For any "
            "Insert Text question, embed the four candidate positions as the "
            "literal markers [A] [B] [C] [D] at sentence boundaries."
        )
    )
    questions: list[Question] = Field(description="The ordered list of questions")


SYSTEM_PROMPT = """\
You are an experienced TOEFL iBT item writer. You produce Reading section \
practice sets that match the official test in structure, tone, and difficulty.

Rules you always follow:
- The passage is academic and self-contained, in the register of a first-year \
university textbook. No first- or second-person address.
- Questions appear in passage order and draw from the official TOEFL Reading \
question types. Standard questions have exactly four options (A-D) with one \
correct answer.
- Include exactly one Insert Text question when asked for 8 or more questions: \
its prompt gives the sentence to be inserted, and the passage contains the \
four literal markers [A] [B] [C] [D] at candidate insertion points.
- The final question is a Prose Summary worth two points: it provides an \
introductory sentence, six options (A-F), and exactly three correct answers \
that capture the passage's major ideas while excluding minor details and \
incorrect statements.
- Every distractor is plausible but defensibly wrong. Explanations cite the \
relevant part of the passage.
"""


def build_user_prompt(topic: str | None, num_questions: int, difficulty: str) -> str:
    lines = [
        f"Write one TOEFL Reading practice set with {num_questions} questions.",
        DIFFICULTY_GUIDANCE[difficulty],
    ]
    if topic:
        lines.append(f"The passage must be about: {topic}.")
    else:
        lines.append(
            "Choose an academic topic suitable for a TOEFL passage (natural "
            "science, social science, or humanities)."
        )
    lines.append(
        "Use a realistic mix of these question types, in passage order: "
        + ", ".join(QUESTION_TYPES)
        + "."
    )
    return "\n".join(lines)


def generate_set(
    client: anthropic.Anthropic,
    *,
    topic: str | None,
    num_questions: int,
    difficulty: str,
    model: str,
) -> ReadingSet:
    """Generate a single reading set via the Claude API."""
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": build_user_prompt(topic, num_questions, difficulty),
            }
        ],
        output_format=ReadingSet,
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(
            "The model declined the request"
            + (f" ({response.stop_details.category})" if response.stop_details else "")
        )
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError(
            "The model response could not be parsed into a reading set "
            f"(stop_reason={response.stop_reason})."
        )
    return parsed


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len] or "set"


def render_text(rset: ReadingSet, *, with_answers: bool = True) -> str:
    """Render a reading set as plain text suitable for the terminal or a .txt file."""
    out: list[str] = []
    out.append(rset.title)
    out.append("=" * len(rset.title))
    out.append(f"Topic: {rset.topic}")
    out.append("")
    out.append(rset.passage.strip())
    out.append("")
    out.append("-" * 60)
    out.append("QUESTIONS")
    out.append("-" * 60)
    for q in rset.questions:
        out.append("")
        out.append(f"{q.number}. [{q.question_type}] {q.prompt}")
        for i, opt in enumerate(q.options):
            out.append(f"    {chr(ord('A') + i)}. {opt}")
    if with_answers:
        out.append("")
        out.append("-" * 60)
        out.append("ANSWER KEY")
        out.append("-" * 60)
        for q in rset.questions:
            out.append("")
            out.append(f"{q.number}. {', '.join(q.correct_letters)}")
            out.append(f"    {q.explanation}")
    return "\n".join(out) + "\n"


def render_html(rset: ReadingSet) -> str:
    """Render a reading set as a self-contained, printable HTML page."""
    e = html.escape

    passage_html = "".join(
        f"<p>{e(para.strip())}</p>"
        for para in re.split(r"\n\s*\n", rset.passage.strip())
        if para.strip()
    )

    questions_html: list[str] = []
    for q in rset.questions:
        opts = "".join(
            f'<li><span class="letter">{chr(ord("A") + i)}.</span> {e(opt)}</li>'
            for i, opt in enumerate(q.options)
        )
        questions_html.append(
            f'<div class="q">'
            f'<p class="q-stem"><span class="q-num">{q.number}.</span> '
            f'<span class="q-type">{e(q.question_type)}</span> {e(q.prompt)}</p>'
            f'<ol class="opts">{opts}</ol>'
            f"</div>"
        )

    answers_html: list[str] = []
    for q in rset.questions:
        answers_html.append(
            f'<li><strong>{q.number}.</strong> {e(", ".join(q.correct_letters))} '
            f'&mdash; <span class="why">{e(q.explanation)}</span></li>'
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(rset.title)} — TOEFL Reading</title>
<style>
  body {{ font-family: Georgia, "Times New Roman", serif; max-width: 46rem;
         margin: 2.5rem auto; padding: 0 1.25rem; line-height: 1.6; color: #1a1a1a; }}
  .kicker {{ font-family: ui-monospace, monospace; font-size: 0.7rem;
            letter-spacing: 0.2em; text-transform: uppercase; color: #b4521f; }}
  h1 {{ font-size: 1.9rem; margin: 0.2rem 0 0.4rem; }}
  .topic {{ color: #555; font-style: italic; margin-bottom: 1.8rem; }}
  .passage p {{ margin: 0 0 1rem; text-align: justify; }}
  hr {{ border: 0; border-top: 1px solid #ddd; margin: 2rem 0; }}
  h2 {{ font-size: 1.1rem; font-family: ui-monospace, monospace;
        letter-spacing: 0.12em; text-transform: uppercase; color: #444; }}
  .q {{ margin: 1.4rem 0; }}
  .q-num {{ font-weight: bold; }}
  .q-type {{ font-family: ui-monospace, monospace; font-size: 0.68rem;
            letter-spacing: 0.08em; text-transform: uppercase; color: #b4521f;
            border: 1px solid #e0c4b4; padding: 0.05rem 0.4rem; border-radius: 3px;
            margin: 0 0.3rem; white-space: nowrap; }}
  ol.opts {{ list-style: none; padding-left: 1.4rem; }}
  ol.opts li {{ margin: 0.3rem 0; }}
  .letter {{ font-weight: bold; color: #555; margin-right: 0.3rem; }}
  details {{ margin-top: 2.5rem; }}
  summary {{ cursor: pointer; font-family: ui-monospace, monospace;
            letter-spacing: 0.12em; text-transform: uppercase; font-size: 0.8rem;
            color: #b4521f; }}
  .answers li {{ margin: 0.6rem 0; }}
  .why {{ color: #555; }}
  @media print {{ details {{ page-break-before: always; }} details[open] summary {{ display: none; }} }}
</style>
</head>
<body>
  <div class="kicker">TOEFL iBT &middot; Reading</div>
  <h1>{e(rset.title)}</h1>
  <div class="topic">{e(rset.topic)}</div>
  <div class="passage">{passage_html}</div>
  <hr>
  <h2>Questions</h2>
  {''.join(questions_html)}
  <details>
    <summary>Show answer key</summary>
    <ol class="answers" style="list-style:none;padding-left:0">{''.join(answers_html)}</ol>
  </details>
</body>
</html>
"""


def write_outputs(
    rset: ReadingSet, out_dir: Path, fmt: str, index: int
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"toefl-reading-{stamp}-{index:02d}-{_slugify(rset.topic)}"
    written: list[Path] = []

    if fmt in ("json", "all"):
        path = out_dir / f"{base}.json"
        path.write_text(rset.model_dump_json(indent=2), encoding="utf-8")
        written.append(path)
    if fmt in ("text", "all"):
        path = out_dir / f"{base}.txt"
        path.write_text(render_text(rset), encoding="utf-8")
        written.append(path)
    if fmt in ("html", "all"):
        path = out_dir / f"{base}.html"
        path.write_text(render_html(rset), encoding="utf-8")
        written.append(path)
    return written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Generate TOEFL iBT Reading practice sets with the Claude API.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--topic", help="Passage topic; if omitted, the model chooses one")
    p.add_argument(
        "--num-questions", type=int, default=10, help="Questions per set (TOEFL uses ~10)"
    )
    p.add_argument(
        "--difficulty",
        choices=sorted(DIFFICULTY_GUIDANCE),
        default="medium",
        help="Target difficulty band",
    )
    p.add_argument("--count", type=int, default=1, help="Number of sets to generate")
    p.add_argument(
        "--format",
        choices=["json", "html", "text", "all"],
        default="all",
        help="Output file format(s)",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=Path("output"),
        help="Directory for generated files",
    )
    p.add_argument("--model", default=DEFAULT_MODEL, help="Claude model ID")
    p.add_argument(
        "--print",
        dest="print_text",
        action="store_true",
        help="Also print each set as text to the terminal",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        sys.stderr.write(
            "ANTHROPIC_API_KEY is not set. Export your key and try again:\n"
            "    export ANTHROPIC_API_KEY=sk-ant-...\n"
        )
        return 2

    if args.num_questions < 1:
        sys.stderr.write("--num-questions must be at least 1.\n")
        return 2
    if args.count < 1:
        sys.stderr.write("--count must be at least 1.\n")
        return 2

    client = anthropic.Anthropic()

    for i in range(1, args.count + 1):
        label = f"set {i}/{args.count}"
        print(f"Generating {label} ({args.difficulty}, {args.num_questions} questions)…")
        try:
            rset = generate_set(
                client,
                topic=args.topic,
                num_questions=args.num_questions,
                difficulty=args.difficulty,
                model=args.model,
            )
        except anthropic.APIError as exc:
            sys.stderr.write(f"API error while generating {label}: {exc}\n")
            return 1
        except RuntimeError as exc:
            sys.stderr.write(f"Could not generate {label}: {exc}\n")
            return 1

        written = write_outputs(rset, args.output, args.format, i)
        print(f"  {rset.title}")
        for path in written:
            print(f"    wrote {path}")
        if args.print_text:
            print()
            print(render_text(rset))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
