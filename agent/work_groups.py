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

The same possessive in front of an ordinal is one work, named the way
people name it and not the way the extract does: "Beethoven's Fifth" is
stored as "Symphony No. 5", and name resolution, finding no such title,
read it as the disco track "A Fifth of Beethoven". The extract has no
aliases, so the nickname is rewritten into the catalogue title here - the
kind stage 1 gave, or the one after the ordinal ("Fifth Piano Concerto"),
or a symphony, which is what a composer's bare ordinal means - and the
creator is kept as related_entity, so it is that composer's No. 5.

And a question about who made a work can come back from stage 1 already
answered. Asked "Who composed The Magic Flute?" it returned works created by
Mozart - the answer it guessed, in place of the work the question names -
and the composer listed Mozart's 22 operas; "Who wrote War and Peace?" came
back as novels by Tolstoy and listed Aleksey Tolstoy's books too. A "who
made" question whose intent asks for works by someone the sentence never
mentions is put back the way it was asked: the person who created the work
named after the verb.

    python work_groups.py          # self-check, no model and no database
"""

import json
import re
import sys

#"Beethoven's symphonies", "the Beatles' albums"
POSSESSIVE = re.compile(r"^(?P<who>.+?)(?:['’]s|(?<=s)['’])\s+(?P<kind>[^'’]+)$")

#plurals that say "works" without saying which kind
GENERIC_KINDS = {"works", "creations", "pieces", "compositions", "things", "titles"}


ORDINALS = {w: n for n, w in enumerate(
    "first second third fourth fifth sixth seventh eighth ninth tenth eleventh twelfth"
    " thirteenth fourteenth fifteenth".split(), start=1)}

#"Beethoven's Fifth", "Beethoven's 9th Symphony", "Fifth Piano Concerto"
NUMBERED = re.compile(r"^(?:(?P<who>.+?)(?:['’]s|(?<=s)['’])\s+)?"
                      r"(?P<nth>[A-Za-z]+|\d{1,2}(?:st|nd|rd|th))"
                      r"(?:\s+(?P<kind>[A-Za-z][A-Za-z ]*?))?$", re.IGNORECASE)


#The kinds a composer's catalogue numbers - the word after the ordinal has to
#be one, or "First Blood" by Stallone would become "Blood No. 1".
NUMBERED_KINDS = {
    "symphony", "concerto", "piano concerto", "violin concerto", "cello concerto",
    "sonata", "piano sonata", "violin sonata", "string quartet", "quartet",
    "piano trio", "suite", "cello suite", "orchestral suite", "partita", "mass",
    "serenade", "nocturne", "etude", "prelude", "ballade", "scherzo", "impromptu",
    "rhapsody", "hungarian rhapsody", "polonaise", "mazurka", "waltz", "divertimento",
    "brandenburg concerto",
}


def _number(nth: str):
    nth = nth.lower()
    if nth in ORDINALS:
        return ORDINALS[nth]
    digits = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)", nth)
    return int(digits.group(1)) if digits else None


def _numbered(name: str, creator, subject):
    """(creator, title) when the name is a creator's numbered work, else None."""
    match = NUMBERED.match(re.sub(r"(?i)^the\s+", "", name.strip()))
    if not match:
        return None
    number = _number(match.group("nth"))
    who, kind = match.group("who"), match.group("kind")
    if number is None or not (who or creator) or not (who or kind):
        #a bare "Fifth" with nobody's name on it is not a title anyone uses
        return None
    if who and creator and not set(who.lower().split()) <= set(creator.lower().split()) | {"the"}:
        return None
    if kind and kind.strip().lower() not in NUMBERED_KINDS:
        return None
    if not kind:
        kind = subject if subject and subject.lower() not in GENERIC_KINDS else "symphony"
    return (who or creator).strip(), f"{kind.strip().title()} No. {number}"


#"Who composed The Magic Flute?" - the verb and the work after it. Only the
#verbs the composer's creator properties answer (author, composer, creator,
#performer, lyricist): the extract holds no director, producer or
#screenwriter rows, so "who directed" would only reach the novel's author.
WHO_MADE = re.compile(
    r"^\s*who\s+(?:(?:first|originally|really|actually)\s+)?"
    r"(?:wrote|composed|painted|created|made|authored|sculpted|drew|sang|recorded|"
    r"penned|is\s+the\s+(?:author|composer|painter|creator)\s+of|"
    r"was\s+the\s+(?:author|composer|painter|creator)\s+of)\s+"
    r"(?P<work>.+?)\s*[?.!]*\s*$", re.IGNORECASE)


def _who_made(intent: dict, sentence: str):
    """The work a "who made X" question names, when stage 1 answered it
    instead of asking it; None otherwise."""
    asked = WHO_MADE.match(sentence)
    if not asked or intent.get("target_type") != "work":
        return None
    related = intent["filters"].get("related_entity")
    if not isinstance(related, dict) or related.get("relation") != "creates":
        return None
    mention = str(related.get("entity_mention") or "")
    words = [w for w in re.findall(r"[^\W\d_]{3,}", mention)]
    if not words or any(re.search(rf"(?i)\b{re.escape(w)}\b", sentence) for w in words):
        #the creator is the sentence's own - "Who wrote Mozart's operas?"
        return None
    return asked.group("work").strip(), mention


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
    if not isinstance(filters, dict):
        return intent_text, []
    turned = _who_made(intent, sentence)
    if turned:
        work, guessed = turned
        intent["target_type"] = "person"
        intent["answer_field"] = None
        intent["filters"] = {key: None for key in filters}
        intent["filters"]["related_entity"] = {"relation": "creates", "entity_mention": work}
        return json.dumps(intent, indent=2, ensure_ascii=False), [
            f"stage 1 answered the question with works by {guessed!r};"
            f" asked instead who created {work!r}"]
    if not isinstance(filters.get("name"), str):
        return intent_text, []
    related = filters.get("related_entity")
    creator = None
    if isinstance(related, dict) and related.get("relation") == "creates":
        creator = related.get("entity_mention") or None
    elif related:
        #linked to something else already; a second link has nowhere to go
        return intent_text, []

    numbered = _numbered(filters["name"], creator, filters.get("subject"))
    if numbered:
        who, title = numbered
        notes = [f"{filters['name']!r} read as {title!r} by {who!r}"
                 " - the catalogue title the extract stores"]
        filters["name"] = title
        if not filters.get("subject"):
            #what it is, so its recordings are not taken for it
            filters["subject"] = title.rsplit(" No. ", 1)[0].lower()
        if not creator:
            filters["related_entity"] = {"relation": "creates", "entity_mention": who}
        return json.dumps(intent, indent=2, ensure_ascii=False), notes

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
        #a numbered work by its nickname
        ("When was Beethoven's Fifth composed?",
         intent("Beethoven's Fifth", "symphony", "Beethoven"), ("Symphony No. 5", "symphony", "Beethoven")),
        ("When was Beethoven's Fifth composed?",
         intent("Beethoven's Fifth"), ("Symphony No. 5", "symphony", "Beethoven")),
        ("When did Beethoven write his 9th symphony?",
         intent("9th symphony", None, beethoven), ("Symphony No. 9", "symphony", beethoven)),
        ("When was First Blood released?", intent("First Blood", "film", "Sylvester Stallone"), None),
        ("When was Stallone's First Blood released?", intent("Stallone's First Blood", "film"), None),
        ("When was Rachmaninoff's Second Piano Concerto written?",
         intent("Rachmaninoff's Second Piano Concerto"),
         ("Piano Concerto No. 2", "piano concerto", "Rachmaninoff")),
        ("When was the Fifth written?", intent("the Fifth"), None),
        ("When was Shakespeare's Hamlet written?", intent("Shakespeare's Hamlet"), None),
        #titles
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
    #"who made X" answered by stage 1: (sentence, stage 1's intent, the work asked about)
    def works_by(creator, subject, target="work"):
        return json.dumps({"target_type": target, "answer_field": None, "filters": {
            "name": None, "occupation": None, "subject": subject, "location": None,
            "domain": "music", "time_constraint": None,
            "related_entity": {"relation": "creates", "entity_mention": creator},
            "compare_entities": None}})
    turned = [
        ("Who composed The Magic Flute?", works_by("Mozart", "opera"), "The Magic Flute"),
        ("Who wrote War and Peace?", works_by("Tolstoy", "novel"), "War and Peace"),
        ("who is the author of Don Quixote", works_by("Miguel de Cervantes", "novel"),
         "Don Quixote"),
        #asked the right way round, or the creator is in the sentence
        ("Who painted the Mona Lisa?", works_by("Mona Lisa", None, "person"), None),
        ("Who wrote Mozart's operas?", works_by("Mozart", "opera"), None),
        ("Which operas did Mozart compose?", works_by("Mozart", "opera"), None),
    ]
    for sentence, given, want in turned:
        text, notes = fill(given, sentence)
        if want is None:
            ok = text == given and not notes
            got = "unchanged" if ok else text
        else:
            parsed = json.loads(text)
            related = parsed["filters"]["related_entity"] or {}
            got = (parsed["target_type"], related.get("entity_mention"), parsed["filters"]["subject"])
            ok = got == ("person", want, None)
        print(f"{'ok  ' if ok else 'FAIL'} {sentence!r}: {got}"
              + (f"  [{'; '.join(notes)}]" if notes else ""))
        failures += not ok
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
