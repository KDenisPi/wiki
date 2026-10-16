#!/usr/bin/env python3
"""Correct the spelling and grammar of a question before anything reads it.

Step 0 of the pipeline: one call to a small model, one sentence back, used as
it comes. The question "Provide list of sientists in England who lived on the
same time as Issak Newton?" had two faults, and both of them cost it an
answer - "sientists" reached stage 1 as an occupation the vocabulary could
not place, and "Issak Newton" reached the composer as a name nothing matched.
The sentence is where both are visible at once, and correcting English is
what a small model is genuinely good at.

Nothing here judges the reply. That is deliberate and it was asked for: the
questions this pipeline gets are written by someone whose first language is
not English, corrections are therefore the normal case rather than the
exception, and a layer that second-guesses the model mostly ends up
second-guessing good corrections and answering the question as typed.

What that choice costs, measured on llama3.1:8b and worth knowing: it
sometimes changes a correctly spelled word for another one - "Which composer
painted the ceiling of the Sistine Chapel?" came back as "Which artist
painted ..." - and on a prompt carrying worked examples it would sometimes
return an example instead of the correction. Those now reach stage 1. If
they turn up in practice the prompt is the first thing to change, and
_self_check below is written to show them rather than hide them. Guards that
asked the extract whether a name or an occupation was real are in e2c673b,
and can come back if the prompt alone is not enough.

The pipeline is not left defenceless either way: resolve_names still rewrites
a name to the extract's spelling after stage 1, which is where a name belongs
and where a misspelling is cheapest to catch.
"""

import logging
import re

logger = logging.getLogger(__name__)


def _tidy(reply: str) -> str:
    """One line of sentence out of whatever the model actually sent.

    The one thing done to a reply, and not a judgement of it: the next stage
    reads a sentence, so one line of sentence is what it gets. The model is
    asked for a bare sentence and usually sends one; the rest of the time it
    wraps it in quotes, puts a label in front of it, or announces it on a
    line of its own - "Here is the corrected sentence:" followed by a blank
    line and then the sentence. None of that is the question, and taking the
    announcement for the question is worse than taking nothing: it sends
    stage 1 a sentence about sentences. A line that ends in a colon is an
    announcement, so it is skipped rather than returned.
    """
    for line in reply.strip().splitlines():
        line = re.sub(r"(?i)^(corrected|corrected sentence|answer|output)\s*:\s*",
                      "", line.strip())
        line = line.strip().strip('"').strip("'").strip()
        if not line or line.endswith(":"):
            continue
        return line
    return ""


def fix(sentence: str, ask) -> tuple:
    """(sentence, note): the question corrected, or exactly as it arrived.

    `ask` is a callable taking the sentence and returning the model's reply,
    so that this module owns no client, URL or model name - the pipeline
    passes its own and the self-check passes one of its own.

    The sentence as typed is always answerable, so neither a model that is
    down nor a reply with nothing in it can cost the pipeline its question.
    Those are the only two cases that fall back; anything else the model says
    is used as the question.
    """
    try:
        reply = ask(sentence)
    except Exception as e:                      # noqa: BLE001 - never fatal
        return sentence, f"not corrected ({e})"

    corrected = _tidy(reply or "")
    if not corrected:
        return sentence, "kept the question as typed - nothing came back"
    if corrected.lower() == sentence.lower():
        return sentence, None
    return corrected, f"corrected to {corrected!r}"


def _differences(before: str, after: str) -> list:
    """What kind of change this was, for a reader deciding about the prompt.

    Reported, never enforced. The point of this step is to fix English, and
    the question worth asking of a run is whether it did only that - so a
    changed number, a changed capitalised name and a change in length are
    each worth naming, because each is a way a correction stops being one.
    """
    notes = []
    words = lambda t: re.findall(r"[A-Za-z0-9']+", t)
    names = lambda t: [w for w in words(t) if w[:1].isupper()][1:]
    lost = [n for n in re.findall(r"\d+", before) if n not in after]
    if lost:
        notes.append(f"number(s) {', '.join(lost)} gone")
    moved = [n for n in names(before)
             if not re.search(rf"\b{re.escape(n)}\b", after, re.I)]
    if moved:
        notes.append(f"name(s) {', '.join(moved)} changed")
    ratio = len(after) / max(len(before), 1)
    if not 0.8 <= ratio <= 1.4:
        notes.append(f"length {ratio:.2f}x")
    added = [w for w in words(after)
             if len(w) > 3 and not re.search(rf"\b{re.escape(w)}\b", before, re.I)]
    if added:
        notes.append(f"added {', '.join(added[:6])}")
    return notes


def _self_check(url: str, model: str, context: str) -> int:
    """Correct a spread of questions and show exactly what came back.

    A report as much as a test. The step has no guards by design, so what
    matters is being able to see whether the model did only what it was
    asked - every correction is printed with what changed in it, and the
    only failures are a reply that was empty or not one line, plus the two
    misspellings this step exists for.
    """
    import sys
    from pathlib import Path
    #OllamaClient lives in the sibling AI_agents repo, the same fixup
    #sentence_to_sql.py does - only the self-check needs it, because fix()
    #is handed a caller's client
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "AI_agents"))
    from OllamaClient import OllamaClient

    template = Path(context).read_text()
    client = OllamaClient(url, model, options={"temperature": 0, "seed": 42,
                                               "max_tokens": 256}, timeout=120)

    def ask(sentence):
        return client.chat_once(template.replace("{{SENTENCE}}", sentence))

    #(sentence, words that have to be in the result)
    cases = [
        ("Provide list of sientists in England who lived on the same time as Issak Newton?",
         ["scientists"]),
        ("Provide list of physican in England who lived on the same time as Robert Hooke did",
         ["physician"]),
        ("Provide list of physician in England who lived on the same time as Issak Newton live?"
         " If it is possible select 10 the most popular.", ["physician"]),
        ("Which composers lived at the same time as Beethowen?", ["Beethoven"]),
        ("Provide list of composer in Germany", ["composer"]),
        #already correct English, which is where an eager model shows itself
        ("Who was the ruler of Russia in 1600?", ["Russia"]),
        ("Which Russian composers lived in the 19th century?", ["composers"]),
        #a real word the asker may have meant differently, and a rare name:
        #both now reach stage 1 as the model leaves them
        ("Which physician discovered the law of gravity?", []),
        ("Which composer painted the ceiling of the Sistine Chapel?", []),
        ("Which physicians lived at the same time as Percivall Willughby?", []),
    ]

    failures = 0
    for sentence, want in cases:
        fixed, note = fix(sentence, ask)
        missing = [w for w in want if w.lower() not in fixed.lower()]
        if missing or not fixed or "\n" in fixed:
            print(f"FAIL {sentence[:56]!r}\n     -> {fixed!r}"
                  + (f"\n     missing {missing}" if missing else ""))
            failures += 1
            continue
        changed = _differences(sentence, fixed) if note else []
        print(f"ok   {sentence[:56]!r}\n     -> {fixed!r}"
              + (f"\n     changed: {'; '.join(changed)}" if changed else ""))

    for original, reply, why in [("Who ruled Russia in 1600?", "", "an empty reply"),
                                 ("Who ruled Russia in 1600?", "\n\n", "blank lines")]:
        fixed, note = fix(original, lambda _s, r=reply: r)
        if fixed != original:
            print(f"FAIL {why} did not fall back: {fixed!r}")
            failures += 1
        else:
            print(f"ok   {why} falls back to the question as typed")

    print("\nall checks passed" if not failures else f"\n{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    url, model = "http://192.168.1.57:11434", "llama3.1:8b"
    context = "sentence_to_sql_stage0_context.txt"
    args = sys.argv[1:]
    while args:
        flag, args = args[0], args[1:]
        if flag == "--url":
            url, args = args[0], args[1:]
        elif flag == "--model":
            model, args = args[0], args[1:]
        elif flag == "--context":
            context, args = args[0], args[1:]
    sys.exit(_self_check(url, model, context))
