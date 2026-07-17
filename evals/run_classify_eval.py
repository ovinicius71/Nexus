"""Mini-eval for the classifier.

Runs the classifier over a JSONL of labeled examples and reports per-field
accuracy. Each line is a JSON object with a ``text`` field plus any labeled
fields to score, e.g.:

    {"text": "comprar leite amanha", "type": "task", "priority": null}
    {"text": "ideia: app de habitos", "type": "idea", "due_date": null}

Only fields present in a line are scored (an explicit ``null`` counts as a
label meaning "should be empty"). Usage:

    python evals/run_classify_eval.py [path/to/examples.jsonl]

Requires ANTHROPIC_API_KEY (from environment or a local .env).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Make the src layout importable when run as a plain script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from organizer.llm.classifier import Classifier  # noqa: E402

DEFAULT_PATH = Path(__file__).resolve().parent / "examples.jsonl"
SCORED_FIELDS = ["type", "title", "due_date", "priority", "project", "people"]


def _predicted(classification, field):
    if field == "type":
        return classification.type.value
    if field == "priority":
        return classification.priority.value if classification.priority else None
    if field == "due_date":
        return classification.due_date.isoformat() if classification.due_date else None
    if field == "people":
        return sorted(n.strip().lower() for n in classification.people)
    return getattr(classification, field)


def _expected(gold, field):
    value = gold[field]
    if field == "people":
        return sorted(n.strip().lower() for n in (value or []))
    return value


def main() -> None:
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ANTHROPIC_API_KEY nao definido (env ou .env).", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    if not path.exists():
        print(f"Arquivo de exemplos nao encontrado: {path}", file=sys.stderr)
        print("Forneca um JSONL rotulado (veja o docstring deste script).", file=sys.stderr)
        sys.exit(1)

    examples = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not examples:
        print("Nenhum exemplo no arquivo.", file=sys.stderr)
        sys.exit(1)

    classifier = Classifier(api_key=api_key)
    correct = {f: 0 for f in SCORED_FIELDS}
    total = {f: 0 for f in SCORED_FIELDS}

    for i, gold in enumerate(examples, 1):
        text = gold["text"]
        try:
            prediction = classifier.classify(text)
        except Exception as exc:  # keep going; report the row
            print(f"[{i}] ERRO ao classificar: {exc}")
            continue
        for field in SCORED_FIELDS:
            if field not in gold:
                continue
            total[field] += 1
            if _predicted(prediction, field) == _expected(gold, field):
                correct[field] += 1

    print(f"\nExemplos: {len(examples)}\n")
    print(f"{'campo':<12} {'acuracia':>10}   (acertos/total)")
    print("-" * 40)
    for field in SCORED_FIELDS:
        if total[field] == 0:
            continue
        acc = correct[field] / total[field]
        print(f"{field:<12} {acc:>9.1%}   ({correct[field]}/{total[field]})")


if __name__ == "__main__":
    main()
