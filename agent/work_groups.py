#!/usr/bin/env python3
"""Read "Beethoven's symphonies" as a kind of work by a creator, not as a title.

Asked "When Ludwig van Beethoven's symphonies were created?", stage 1 returned
the target as a work with name "Beethoven's symphonies", subject "symphony"
and the creator as related_entity. Name resolution then read the name as the
title "Beethoven Symphonies", the composer - a name picks one entity out -
dropped the subject beside it, and looked for one musical work of that title
by Beethoven. There is none, and the answer was "Nothing in the extract
matches that", where the extract has all nine symphonies with their years.

A creator's possessive in front of a lowercase plural is a group of the
creator's works of that kind, so here, after stage 1 and before the names are
resolved:

  - the name is cleared;
  - the plural, made singular, becomes the subject if stage 1 left it empty
    ("works", "pieces" and the like name no kind, and leave it empty);
  - the creator becomes related_entity "creates" if stage 1 left that empty.

A title is not touched: "Beethoven's Fifth" is not plural, and "Shakespeare's
Sonnets" is capitalised in the sentence, the way a title is written. Nor is
a name without the possessive unless its other words are the creator stage 1
already gave - "Beethoven symphonies" with Ludwig van Beethoven as creator.

    python work_groups.py          # self-check, no model and no database
"""

import json
import re
import sys

#"Beethoven's symphonies", "the Beatles' albums"
POSSESSIVE = re.compile(r"^(?P<who>.+?)(?:['’]s|(?<=s)['’])\s+(?P<kind>[^'’]+)$")

#plurals that say "works" without saying which kind
GENERIC_KINDS = {"works", "creations", "pieces", "compositions", "things", "titles"}


def _singular(word: str) -> str:
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if re.search(r"(ss|x|z|ch|sh)es$", word):
        return word[:-2]
    return word[:-1]


def _as_written(kind: str, sentence: str) -> str:
    """The kind as the sentence spells it - stage 1 may have changed its case."""
    found = re.search(re.escape(kind), sentence, re.IGNORECASE)
    return found.group(0) if found else kind


def _is_kind(kind: str, sentence: str) -> bool:
    """A lowercase plural, as the sentence writes it."""
    written = _as_written(kind, sentence)
    words = written.split()
    return (bool(words) and written == written.lower()
            and all(re.fullmatch(r"[a-z-]+", w) for w in words)
            and words[-1].endswith("s") and not words[-1].endswith("ss")
            and len(words[-1]) > 3)


def _split(name: str, creator: str | None, sentence: str):
    """(creator, kind) when the name is a creator's works of a kind, else None."""
    name = re.sub(r"(?i)^the\s+(?=\S+['’])", "", name.strip())
    possessive = POSSESSIVE.match(name)
    if possessive:
        who, kind = possessive.group("who").strip(), possessive.group("kind").strip()
        if not _is_kind(kind, sentence):
            return None
        if creator and not set(who.lower().split()) <= set(creator.lower().split()) | {"the"}:
            #someone else's works - "Mozart's operas that Beethoven admired"
            return None
        return who, kind
    #"Beethoven symphonies": only with the creator stage 1 gave
    if not creator:
        return None
    creator_words = set(creator.lower().split())
    words = name.split()
    for cut in range(1, len(words)):
        who, kind = words[:cut], " ".join(words[cut:])
        if {w.lower() for w in who} <= creator_words and _is_kind(kind, sentence):
            return " ".join(who), kind
    return None


def fill(intent_text: str, sentence: str) -> tuple:
    """Returns (intent_text, notes); the same string back when nothing changed."""
    try:
        intent = json.loads(intent_text)
    except (json.JSONDecodeError, TypeError):
        return intent_text, []
    if not isinstance(intent, dict) or intent.get("target_type") != "work":
        return intent_text, []
    filters = intent.get("filters")
    if not isinstance(filters, dict) or not isinstance(filters.get("name"), str):
        return intent_text, []
    related = filters.get("related_entity")
    creator = None
    if isinstance(related, dict) and related.get("relation") == "creates":
        creator = related.get("entity_mention") or None
    elif related:
        #linked to something else already; a second link has nowhere to go
        return intent_text, []

    split = _split(filters["name"], creator, sentence)
    if not split:
        return intent_text, []
    who, kind = split
    name = filters["name"]
    filters["name"] = None
    notes = [f"{name!r} is {kind} by {who!r}, not a title - the name is dropped"]
    last = kind.split()[-1].lower()
    if not filters.get("subject") and last not in GENERIC_KINDS:
        words = kind.lower().split()
        filters["subject"] = " ".join(words[:-1] + [_singular(words[-1])])
        notes.append(f"subject {filters['subject']!r} read from {kind!r}")
    if not creator:
        filters["related_entity"] = {"relation": "creates", "entity_mention": who}
        notes.append(f"related_entity: created by {who!r}")
    return json.dumps(intent, indent=2, ensure_ascii=False), notes


def _self_check() -> int:
    """Sentences and what each must come out as; no model, no database."""
    def intent(name, subject=None, creator=None, target="work", relation="creates"):
        return json.dumps({"target_type": target, "answer_field": "time", "filters": {
            "name": name, "occupation": None, "subject": subject, "location": None,
            "domain": "music", "time_constraint": None,
            "related_entity": ({"relation": relation, "entity_mention": creator}
                               if creator else None),
            "compare_entities": None}})

    beethoven = "Ludwig van Beethoven"
    cases = [
        #(sentence, stage 1's intent, (name, subject, creator) afterwards or None = unchanged)
        ("When Ludwig van Beethoven's symphonies were created?",
         intent("Beethoven's symphonies", "symphony", beethoven), (None, "symphony", beethoven)),
        ("When were Beethoven's symphonies written?",
         intent("Beethoven's symphonies"), (None, "symphony", "Beethoven")),
        ("List Mozart's operas", intent("Mozart's operas"), (None, "opera", "Mozart")),
        ("Which of the Beatles' albums came out in 1969?",
         intent("the Beatles' albums"), (None, "album", "Beatles")),
        ("When were Beethoven symphonies composed?",
         intent("Beethoven symphonies", None, beethoven), (None, "symphony", beethoven)),
        ("Show me Bach's works", intent("Bach's works"), (None, None, "Bach")),
        ("When did Haydn write his string quartets?",
         intent("Haydn's string quartets"), (None, "string quartet", "Haydn")),
        #titles
        ("When was Beethoven's Fifth composed?", intent("Beethoven's Fifth"), None),
        ("When were Shakespeare's Sonnets published?", intent("Shakespeare's Sonnets"), None),
        ("When was the Mona Lisa painted?", intent("Mona Lisa", "painting"), None),
        ("When was Moonlight Sonata written?",
         intent("Moonlight Sonata", None, beethoven), None),
        #not a work, or linked to something else
        ("When was Beethoven's symphonies' premiere?",
         intent("Beethoven's symphonies", target="event"), None),
        ("Mozart's operas performed in Vienna",
         intent("Mozart's operas", creator="Vienna", relation="located_in"), None),
        ("not json", "not json", None),
    ]
    failures = 0
    for sentence, given, want in cases:
        text, notes = fill(given, sentence)
        if want is None:
            ok = text == given and not notes
            got = "unchanged" if ok else text
        else:
            f = json.loads(text)["filters"]
            got = (f["name"], f["subject"], (f["related_entity"] or {}).get("entity_mention"))
            ok = got == want
        print(f"{'ok  ' if ok else 'FAIL'} {sentence!r}: {got}"
              + (f"  [{'; '.join(notes)}]" if notes else ""))
        failures += not ok
    print("\nall checks passed" if not failures else f"\n{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_self_check())
