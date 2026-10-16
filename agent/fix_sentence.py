#!/usr/bin/env python3
"""Correct the spelling and grammar of a question before it is read.

A layer asked for after "Provide list of sientists in England who lived on the
same time as Issak Newton?" went through the pipeline. Two things were wrong
with that sentence and only one of them mattered: "sientists" survived,
because an occupation is looked up in a vocabulary that stage 1 normalises
into, and "Issak Newton" did not, because a name is matched literally. The
name is now resolve_names.py's problem. This is the rest of it - the sentence
itself, corrected once, before any of the three stages reads it.

What it cannot do, and is told not to try: "physician" where the asker meant
"physicist" is not a misspelling. Both are words, the question that used the
first one was answered correctly - 152 doctors alive in Robert Hooke's
lifetime, with neither Hooke nor Newton among them, because neither practised
medicine - and a layer that rewrote it would have invented a question nobody
asked. Spelling has a right answer and intent does not, so this corrects
spelling and leaves meaning alone. The prompt says so with examples, and
_acceptable refuses a reply that rewrote the sentence rather than fixing it.

The guards matter more than the prompt. An 8B model asked to edit a sentence
will sometimes answer it, sometimes explain the edit, and sometimes return
the sentence with a word of its own invention in place of a name it did not
recognise. None of those can be allowed through, and none of them need a
model to detect: a reply is taken only if it is one line, close to the
original in length, and still made of mostly the same words. Anything else
leaves the sentence exactly as the asker typed it, which is the behaviour
this layer replaces and therefore a safe thing to fall back to.
"""

import logging
import re

#the same budget the name resolver uses - one slip in a short word, two in a
#longer one - so that "a respelling" means one thing in this project
from intent_to_sql import _typo_budget

logger = logging.getLogger(__name__)

#How far a correction may stray before it is refused. A corrected sentence is
#the same sentence: "sientists" to "scientists" is one word of thirteen, and
#a reply that shares half its words with the question has not corrected it.
LENGTH_RATIO = (0.6, 1.6)
KEPT_WORDS = 0.6
#words too short to carry the comparison - every sentence has these
SMALL = 3


def _distance(a: str, b: str) -> int:
    """Levenshtein distance, which is all the guards below need.

    Plain rather than Damerau: a transposition costs two here instead of
    one, so a transposed four-letter name is refused where the SQL-side rule
    would allow it. Refusing a correction keeps the asker's sentence, which
    is the safe direction to be wrong in.
    """
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        row = [i]
        for j, cb in enumerate(b, 1):
            row.append(min(previous[j] + 1, row[j - 1] + 1,
                           previous[j - 1] + (ca != cb)))
        previous = row
    return previous[-1]


def _names(text: str) -> list:
    """The capitalised phrases, minus the words capitalised by position.

    A name is where a correction does the most damage, and the first word of
    every sentence is capitalised for reasons that have nothing to do with
    being one - so "Provide" and "Which" are skipped and "Newton" is not.

    Runs of capitalised words are kept together, because a single word is
    not a name and cannot be checked like one: "Issak" on its own is a word
    the extract carries - Friedrich Issak, seven sitelinks - while "Issak
    Newton" is a name it has never heard of.
    """
    found = []
    for part in re.split(r"[.?!]+", text):
        run = []
        for word in re.findall(r"[A-Za-z][A-Za-z'-]*", part)[1:]:
            if word[:1].isupper():
                run.append(word)
                continue
            if run:
                found.append(" ".join(run))
                run = []
        if run:
            found.append(" ".join(run))
    return found


def _words(text: str) -> list:
    """The words worth comparing: lowercased, long enough to mean something."""
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > SMALL]


def _tidy(reply: str) -> str:
    """One line of sentence out of whatever the model actually sent.

    It is asked for a bare sentence and usually sends one. The rest of the
    time it sends the sentence with a label in front of it, in quotes, after
    a blank line, or followed by a paragraph about what it changed - so the
    first non-empty line is taken and the label and quotes come off it.
    """
    for line in reply.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"(?i)^(corrected|corrected question|answer|output)\s*:\s*", "", line)
        line = line.strip().strip('"').strip("'").strip()
        if line:
            return line
    return ""


def _held(name: str, text: str) -> bool:
    """Is this name still in the sentence - on its own or inside a longer one.

    "Newton" becoming "Isaac Newton" is a name expanded, not a name replaced,
    and refusing that correction was wrong. A word-bounded search says so,
    where comparing lists of phrases could not.
    """
    return bool(re.search(rf"\b{re.escape(name)}\b", text, re.I))


def _acceptable(original: str, corrected: str, known=None, occupation=None):
    """None if the correction may be used, or the reason it may not.

    Three ways a reply is not a correction of this sentence, all of them seen
    from llama3.1:8b on these questions: nothing at all, an answer or a
    commentary where a sentence was asked for (which shows up as length), and
    a sentence rebuilt around different words.
    """
    if not corrected:
        return "nothing usable in the reply"
    if corrected.lower() == original.lower():
        return None

    before, after = _words(original), _words(corrected)
    if not before:
        return None
    ratio = len(corrected) / max(len(original), 1)
    if not LENGTH_RATIO[0] <= ratio <= LENGTH_RATIO[1]:
        return f"length changed by {ratio:.2f}x, which is a rewrite, not a correction"

    kept = sum(1 for w in before if w in after) / len(before)
    if kept < KEPT_WORDS:
        return f"only {kept:.0%} of the words survived, which is a different question"

    #A number is never a spelling mistake. "select 10 the most popular" came
    #back as "a list of ten", and a question that asks for ten results has to
    #keep saying 10 where the next stage can read it - all the more once the
    #intent has a field for it. Years are the same case and the worse one.
    lost = [n for n in re.findall(r"\d+", original) if n not in corrected]
    if lost:
        return f"the number{'s' if len(lost) > 1 else ''} {', '.join(lost)} went missing"

    #A name may be respelled and may not be replaced. This is the guard that
    #earns the layer: llama3.1:8b turned "Percivall Willughby" - a real
    #physician, spelled correctly - into "Peregrine Willughby", and turned
    #"Who ruled Russia in 1600?" into "Who ruled France in 1600?". Both kept
    #enough words to pass every other test here. A correction of a name is
    #close to it: "Issak" to "Isaac" is two edits, "Beethowen" to
    #"Beethoven" is one, "Percivall" to "Peregrine" is six and "Russia" to
    #"France" is not a spelling of anything.
    kept_names = _names(corrected)
    for name in _names(original):
        if _held(name, corrected):
            continue
        #A name the extract already uses is not a misspelling of anything,
        #and no edit distance can say so: "Percivall Willughby" to "Percival
        #Willughby" is one edit, exactly like "Issak" to "Isaac", and the
        #first is a real physician while the second is a typo. Only the dump
        #knows which, and asking it costs 0.33s - see resolve_names.carried.
        if known and known(name):
            return f"the extract carries {name!r} as written"
        budget = sum(_typo_budget(word) for word in name.split())
        if any(_distance(name.lower(), other.lower()) <= budget
               for other in kept_names):
            continue
        return f"{name!r} was replaced rather than respelled"

    #And the same question for the words that are not names. An occupation
    #swapped for another occupation is the failure this whole layer was
    #argued about: "physician" for "physicist" is two edits, inside the
    #budget that "Issak" to "Isaac" needs, so distance cannot tell them
    #apart - but the extract files people under both words, and under
    #neither "physicians" nor "sientists", which is exactly the line between
    #a word respelled and a word replaced. Only asked when something
    #occupational went missing, so a correction that touched no such word
    #costs nothing.
    if occupation:
        dropped = [w for w in before if not _held(w, corrected) and occupation(w)]
        if dropped:
            gained = [w for w in after if not _held(w, original) and occupation(w)]
            if gained:
                return (f"{dropped[0]!r} became {gained[0]!r}, and the extract files"
                        f" people under both - that is a different question")
    return None


def fix(sentence: str, ask, known=None, occupation=None) -> tuple:
    """(sentence, note): the question corrected, or exactly as it arrived.

    `ask` is a callable taking the filled prompt and returning the reply, so
    that this module does not own a client, a URL or a model name - the
    pipeline passes its own, and the self-check passes one of its own too.
    `known` and `occupation` are the same arrangement for the database: two
    callables answering "does the extract use this name, spelled like this?"
    and "does it file people under this word?". They are what separate a
    word corrected from a word replaced. Without them the sentence is still
    corrected, and a plausible wrong name or a swapped occupation can get
    through - resolve_names.carried and .occupations build them.

    A note is returned whenever the sentence changed or a reply was refused,
    because both are things a reader of the log needs to see: the first says
    which question was actually answered, and the second says that one was
    offered and thrown away.
    """
    try:
        reply = ask(sentence)
    except Exception as e:                      # noqa: BLE001 - never fatal
        #the question as typed is always answerable; a correction is a bonus,
        #and a model that is down must not cost the pipeline its sentence
        return sentence, f"not corrected ({e})"

    corrected = _tidy(reply or "")
    refused = _acceptable(sentence, corrected, known, occupation)
    if refused:
        return sentence, f"kept the question as typed - {refused}"
    if corrected.lower() == sentence.lower():
        return sentence, None
    return corrected, f"corrected to {corrected!r}"


def _self_check(url: str, model: str, context: str, db_path: str) -> int:
    """Correct the questions this layer was asked for, and some it must not.

    The sentences below are deliberately not the ones in the prompt's
    examples, so that what is measured is the model correcting English rather
    than the model copying an answer it was shown.
    """
    import sys
    from pathlib import Path
    #OllamaClient lives in the sibling AI_agents repo, the same fixup
    #sentence_to_sql.py does - only the self-check needs it, because fix()
    #is handed a caller's client
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "AI_agents"))
    from OllamaClient import OllamaClient

    from resolve_names import carried, occupations

    known, occupation = carried(db_path), occupations(db_path)
    template = Path(context).read_text()
    client = OllamaClient(url, model, options={"temperature": 0, "seed": 42,
                                               "max_tokens": 256}, timeout=120)

    def ask(sentence):
        return client.chat_once(template.replace("{{SENTENCE}}", sentence))

    #(sentence, words that have to be in the result, words that must not be)
    cases = [
        #the two questions this layer was asked for
        ("Provide list of sientists in England who lived on the same time as Issak Newton?",
         ["scientists"], ["sientists"]),
        ("Provide list of physician in England who lived on the same time as Issak Newton live?"
         " If it is possible select 10 the most popular.",
         ["10"], ["physicist", "physicists"]),
        #a question whose only fault is a name
        #the misspelling Denis tested by hand, which is a real one - unlike
        #"physician", which is a word and has to survive untouched
        ("Provide list of physican in England who lived on the same time as Robert Hooke did",
         ["physician"], ["physicist", "physican"]),
        ("Which composers lived at the same time as Beethowen?", ["Beethoven"], ["Beethowen"]),
        #pluralising an occupation is a grammar fix and has to survive the
        #guard that refuses swapping one occupation for another
        ("Provide list of composer in Germany", ["composers"], ["artist"]),
        #correct English, which has to come back as it is
        ("Who was the ruler of Russia in 1600?", ["ruler", "Russia", "1600"], []),
        ("Which Russian composers lived in the 19th century?",
         ["Russian", "composers", "19th"], []),
        #a real word the asker may have meant differently: not this layer's
        #business, and the case that made the whole layer worth arguing about
        ("Provide list of physician in England who lived on the same time as Robert Hooke did",
         ["physician"], ["physicist"]),
        #a correct but unusual name must survive: the model has every
        #incentive to "fix" one it does not know
        ("Which physicians lived at the same time as Percivall Willughby?",
         ["Percivall Willughby"], []),
    ]

    failures = 0
    for sentence, want, unwanted in cases:
        fixed, note = fix(sentence, ask, known, occupation)
        missing = [w for w in want if w.lower() not in fixed.lower()]
        present = [w for w in unwanted if re.search(rf"\b{re.escape(w)}\b", fixed, re.I)]
        if missing or present:
            print(f"FAIL {sentence[:52]!r}\n     -> {fixed!r}")
            if missing:
                print(f"     missing {missing}")
            if present:
                print(f"     should not say {present}")
            failures += 1
            continue
        print(f"ok   {sentence[:52]!r}\n     -> {fixed!r}")
        if note and not note.startswith("corrected"):
            print(f"     note: {note}")

    #and the guards, which need no model at all
    for original, reply, why in [
        ("Who ruled Russia in 1600?", "", "empty reply"),
        ("Who ruled Russia in 1600?",
         "Boris Godunov ruled Russia in 1600. He was the Tsar of Russia from"
         " 1598 until his death in 1605, and his reign is remembered for the"
         " famine that began in 1601.", "an answer instead of a correction"),
        ("Who ruled Russia in 1600?", "Who ruled France in 1600?", "a different question"),
        #one edit, and the only thing that knows it is wrong is the dump
        ("Which physicians lived at the same time as Percivall Willughby?",
         "Which physicians lived at the same time as Percival Willughby?",
         "a real name respelled by one letter"),
        #the swap this layer exists to not make
        ("Which physician discovered the law of gravity?",
         "Which physicist discovered the law of gravity?",
         "one occupation swapped for another"),
        ("Which composer painted the ceiling of the Sistine Chapel?",
         "Which artist painted the ceiling of the Sistine Chapel?",
         "composer for artist"),
    ]:
        fixed, note = fix(original, lambda _s, r=reply: r, known, occupation)
        if fixed != original:
            print(f"FAIL guard let {why} through: {fixed!r}")
            failures += 1
        else:
            print(f"ok   guard refused {why}: {note}")

    print("\nall checks passed" if not failures else f"\n{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    url, model = "http://192.168.1.57:11434", "llama3.1:8b"
    context = "sentence_to_sql_stage0_context.txt"
    db_path = "/home/denis/projects/wiki_data/run7/wiki.duckdb"
    args = sys.argv[1:]
    while args:
        flag, args = args[0], args[1:]
        if flag == "--url":
            url, args = args[0], args[1:]
        elif flag == "--model":
            model, args = args[0], args[1:]
        elif flag == "--context":
            context, args = args[0], args[1:]
        elif flag == "--db":
            db_path, args = args[0], args[1:]
    sys.exit(_self_check(url, model, context, db_path))
