# TOEFL Reading Set Generator

A command-line tool that generates TOEFL iBT **Reading** practice sets — an
academic passage plus a batch of questions in the official question-type mix —
using the Claude API.

Each set includes:

- A self-contained academic passage at a chosen difficulty band.
- Questions in passage order drawn from the official TOEFL Reading question
  types: Factual Information, Negative Factual Information, Inference,
  Rhetorical Purpose, Vocabulary, Reference, Sentence Simplification, Insert
  Text, and a two-point Prose Summary.
- An answer key with a short rationale for every question.

## Setup

```bash
cd toefl-set-generator
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
# One medium set, model picks the topic, JSON + HTML + text into ./output
python toefl_set_generator.py

# Three hard sets about a specific topic, 12 questions each, JSON only
python toefl_set_generator.py \
  --count 3 --difficulty hard \
  --topic "the formation of galaxies" \
  --num-questions 12 --format json

# One easy set, also printed to the terminal
python toefl_set_generator.py --difficulty easy --print
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--topic` | (model chooses) | Passage subject |
| `--num-questions` | `10` | Questions per set |
| `--difficulty` | `medium` | `easy`, `medium`, or `hard` |
| `--count` | `1` | Number of sets to generate |
| `--format` | `all` | `json`, `html`, `text`, or `all` |
| `--output` | `output/` | Directory for generated files |
| `--model` | `claude-opus-4-8` | Claude model ID |
| `--print` | off | Also print each set as text |

## How it works

The generator calls the Claude API (`messages.parse`) with a structured-output
schema, so each response comes back as a validated `ReadingSet` object rather
than free text. Adaptive thinking is enabled so the model can plan the passage
and questions before writing them. Output is rendered to:

- **JSON** — the raw structured set, for programmatic use.
- **HTML** — a clean, printable page with a collapsible answer key.
- **Text** — a plain-text version with the answer key appended.

## Notes

- The HTML answer key is collapsed behind a "Show answer key" toggle and starts
  on a new page when printed, so a set can be handed out without the answers.
- Insert Text questions embed the four candidate positions as the literal
  markers `[A] [B] [C] [D]` in the passage.
