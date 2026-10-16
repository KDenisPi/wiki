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

    The sentence as typed is always answerable, so a model that is down, a
    reply with nothing in it, or a correction carrying a number the question
    never mentioned all leave the question exactly as it arrived. Nothing
    else is judged.

    That third one is the only thing here that inspects a correction, and it
    is in because a rule in the prompt did not hold it. "Russia leaders lived
    on the same time with Isaac Newton?" came back as "Russia's leaders lived
    on the 17th century with Isaac Newton?" - the broken "on the same time"
    repaired by inventing a century, which turns a question anchored on a
    person into a question about a date range and drops Newton from it
    entirely. Three runs out of three. A number the sentence does not contain
    is new information rather than better English, and is the one kind of
    change that cannot be a correction.
    """
    try:
        reply = ask(sentence)
    except Exception as e:                      # noqa: BLE001 - never fatal
        return sentence, f"not corrected ({e})"

    corrected = _tidy(reply or "")
    if not corrected:
        return sentence, "kept the question as typed - nothing came back"
    invented = [n for n in re.findall(r"\d+", corrected)
                if n not in re.findall(r"\d+", sentence)]
    if invented:
        return sentence, (f"kept the question as typed - it says nothing about"
                          f" {', '.join(invented)}")
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
    """Correct a spread of questions, and check it corrected only those.

    A report as much as a test: the step has no guards by design, so every
    correction is printed with what changed in it. What is asserted is what
    the prompt promises - the typos are fixed, the words that were already
    right survive, every number stays a number, and a sentence with nothing
    wrong comes back untouched.

    The last two are the ones that cost a prompt revision to win. The first
    wording lost them: "in the 19th century" came back as "during the
    nineteenth century", "select 10" as "select ten", "composer" as
    "artist", "Percivall" as "Percival", and "discovered" grew into "is
    credited with discovering" - all of them on input that needed no
    correcting, which is where this model is least safe. Naming the ordinal
    in the prompt is what finally held: 12/12 here and 0 of 12 lost across
    three consecutive runs, where the first wording lost 3 and rewrote 4 of
    the 5 already-correct sentences.
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

    #(sentence, what has to survive it, is it already correct English)
    cases = [
        ("Provide list of sientists in England who lived on the same time as Issak Newton?",
         ["scientists", "England"], False),
        ("Provide list of physican in England who lived on 18th centery with"
         " Percivall Willughby", ["physician", "18th", "Percivall Willughby"], False),
        ("Provide list of physican in England who lived on the same time as Robert Hooke did",
         ["physician", "Robert Hooke"], False),
        ("Provide list of physician in England who lived on the same time as Issak Newton live?"
         " If it is possible select 10 the most popular.", ["physician", "10"], False),
        ("Which composers lived at the same time as Beethowen?", ["Beethoven"], False),
        ("Provide list of composer in Germany", ["composer", "Germany"], False),
        ("Which Russian composers lived in 19th centery?", ["19th", "century"], False),
        #broken English that the model repaired by inventing a date: it read
        #"lived on the same time with Isaac Newton" as "lived on the 17th
        #century with Isaac Newton". Whatever comes back, 17 is not in the
        #question and the question is what gets used.
        ("Russia leaders lived on the same time with Isaac Newton?",
         ["Russia", "Isaac Newton"], False),
        #correct English, which is where an eager model shows itself: a word
        #swapped for another word, a number spelled out, a rare name
        #"corrected" into a commoner one, a verb grown into a clause
        ("Which Russian composers lived in the 19th century?", ["19th"], True),
        ("Who was the ruler of Russia in 1600?", ["1600", "Russia"], True),
        ("Which physician discovered the law of gravity?", ["physician"], True),
        ("Which physicians lived at the same time as Percivall Willughby?",
         ["Percivall Willughby"], True),
    ]

    #Printed, not asserted, because no prompt has ever held it. The sentence
    #asks which composer painted a ceiling, which is false as well as odd, so
    #the model corrects the fact and answers "Which artist painted ...". Four
    #wordings have been measured against it: the asker's own, a 739-character
    #rules-only one, this one with "do not replace a word that is spelled
    #correctly" added, and a 1501-character version naming this very swap as
    #a counter-example. All four swapped it. The only thing that held it was
    #asking the extract whether both words were occupations it files people
    #under, which is in e2c673b and was taken out on purpose. So it is here
    #to be seen rather than to pass, and a run that leaves it alone is the
    #model having a better day, not the prompt having improved.
    watched = ["Which composer painted the ceiling of the Sistine Chapel?"]

    def held(needle, text):
        #a plural is a grammar fix and not a loss: "physician" to
        #"physicians" is what this step is for, "composer" to "artist" is not
        return bool(re.search(rf"\b{re.escape(needle)}(s|es)?\b", text, re.I))

    def same_question(before, after):
        return before.strip().rstrip(".?").lower() == after.strip().rstrip(".?").lower()

    failures = 0
    for sentence, must, already_right in cases:
        fixed, note = fix(sentence, ask)
        lost = [w for w in must if not held(w, fixed)]
        rewritten = already_right and not same_question(sentence, fixed)
        if lost or rewritten or not fixed or "\n" in fixed:
            print(f"FAIL {sentence[:56]!r}\n     -> {fixed!r}")
            if lost:
                print(f"     lost {lost}")
            if rewritten:
                print("     rewrote a sentence that was already correct")
            failures += 1
            continue
        changed = _differences(sentence, fixed) if note else []
        print(f"ok   {sentence[:56]!r}\n     -> {fixed!r}"
              + (f"\n     changed: {'; '.join(changed)}" if changed else ""))

    #the gate, checked without a model, because a prompt rule holding today
    #is not the same as the pipeline being safe if it stops holding
    for sentence in watched:
        fixed, _ = fix(sentence, ask)
        verdict = "left alone" if fixed.strip() == sentence.strip() else "CHANGED"
        print(f"watch {sentence!r}\n     -> {fixed!r}\n     {verdict}")

    for original, reply, why in [
            ("Who ruled Russia in 1600?", "", "an empty reply"),
            ("Who ruled Russia in 1600?", "\n\n", "blank lines"),
            ("Russia leaders lived on the same time with Isaac Newton?",
             "Russia's leaders lived on the 17th century with Isaac Newton?",
             "a century the question never mentioned"),
            ("Who ruled Russia in 1600?", "Who ruled Russia in 1605?",
             "a year changed for another")]:
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
