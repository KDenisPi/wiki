#!/usr/bin/env python3
"""Resolve the names a question uses to the names the extract carries.

Stage 1 copies a name through exactly as the sentence spelled it, and it is
right to: it cannot know which of 12 million labels was meant, and a model
that tidies a name is a model that quietly answers about someone else. The
cost was that a misspelled name ended the pipeline with a sentence about the
data. Nothing matched "Issak Newton", so the anchor CTE was empty, the window
built from it was NULL, every date test against NULL was NULL, and a question
with 152 answers - English physicians alive in Newton's lifetime - came back
as "Nothing in the extract matches that." That is a claim about the dump. The
claim this layer makes instead is about the spelling.

Why a layer, and not a looser match inside the composed query, which is where
the matching for everything else lives: the looser match cannot be made
cheap. Measured against run7, 12,220,506 items:

    regexp_matches on a word boundary                      0.3s
    per-word edit distance over every label               7-10s
    both, OR-ed together, name spelled correctly          7-10s

The third line is the one that decides it. An OR evaluates its right side for
every row the cheap side rejected, which is almost every row, so the composer
would pay the full cost on every question whether or not the name needed
rescuing. Bounding the distance to notable items alone (sitelinks >= 1, 5.6M
of the 12.2M) cuts the candidates from 143 to 56 and the time not at all:
9.21s to 9.22s. Requiring one word of a name to be spelled right does make it
cheap - 0.27s - but every one of the 15 anchor mentions in the gold corpus is
a single word ("Beethoven", "Newton", "Mozart"), and a single word has no
other word to be anchored by. A chunk-pigeonhole prefilter is cheap and
unsound: a transposition damages two adjacent chunks at a cost of one edit,
which drops real matches - 186 rows where the unbounded test finds 203.

So the lookup happens once, here, against the two label columns, and the
composed query keeps the cheap match. A name spelled correctly costs one
0.3s query and is never rewritten; a misspelled one costs that plus a single
8s lookup, and then the query the composer builds is as fast as any other.

The other thing a layer buys is being able to say so. The pipeline can now
report "read 'Issak Newton' as Isaac Newton", which is a claim the reader can
check, and distinguish a name it could not place at all from a question with
no answer - two outcomes that were both "nothing matches" before.
"""

import json
import logging

#The private helpers are imported on purpose. The question this module asks
#first - "is the name already spelled the way the composer will look for it?"
#- is only answered correctly by the expression the composer really runs. A
#copy of the matching rules here would drift, and every drift is either a
#rewrite of a name that needed none or a name left misspelled.
from intent_to_sql import I_LABEL, _fuzzy_match, _title_match, _word_match

logger = logging.getLogger(__name__)

#the label the extract shows a reader, same coalesce the composer projects
LABEL = 'coalesce(i."label", i.label_ru)'

#How a name arrives in an intent. A mention in filters.name is the item the
#answer is about and is matched by title - internal spaces are wildcards,
#because "Symphony 5" has to reach "Symphony No. 5". Everywhere else a name
#identifies an entity the target is related to, and is matched by word.
BY_TITLE, BY_WORD = "title", "word"


def _spelled(mention: str, how: str) -> str:
    """The composer's own test for "this name is in the extract as written"."""
    if how == BY_TITLE:
        return (f"({_title_match(I_LABEL, mention)}"
                f" OR {_title_match('i.label_ru', mention)})")
    return _word_match(LABEL, mention)


def _resolve_one(con, mention: str, how: str):
    """(name, note) for one mention: the extract's spelling of it, or None.

    None means no label in the extract is within a typo of the name, which is
    worth saying out loud - it is the difference between a question nobody
    answers and a question about nobody.

    The close match is ranked by sitelinks for the same reason the anchor is:
    among the labels a typo can reach, the best known is the one a question
    about a typo'd name meant. "Issak Newton" reaches 104 labels and Isaac
    Newton has 300 sitelinks.
    """
    if con.execute(f"SELECT 1 FROM items i"
                   f" WHERE {_spelled(mention, how)} LIMIT 1").fetchone():
        return mention, None

    row = con.execute(
        f"SELECT {LABEL} FROM items i WHERE {_fuzzy_match(LABEL, mention)}"
        f" ORDER BY (SELECT sitelinks FROM sites s WHERE s.qid = i.qid)"
        f" DESC NULLS LAST LIMIT 1").fetchone()
    if not row or not row[0]:
        return None, f"no label in the extract is close to {mention!r}"
    return row[0], f"read {mention!r} as {row[0]!r}"


def resolve(intent_text: str, db_path: str) -> tuple:
    """Rewrite the names in a stage-1 intent to the extract's spelling.

    Returns (intent_text, notes, unplaced): the intent as JSON text again so
    that the caller can hand the same string to the stage-2 prompt, to the
    composer and to the training log - a record built from a different intent
    than the one the pipeline ran is worse than no record.

    Every failure here leaves the intent exactly as it arrived. A missing
    duckdb package, a database that is not there, a reply that is not an
    intent: none of them are reasons to stop, because the composer handles an
    unresolved name no worse than it did before this module existed.
    """
    try:
        parsed = json.loads(intent_text)
    except (json.JSONDecodeError, TypeError):
        #stage 1 returned something that is not an intent; the composer says
        #so with the parse error, which is a better message than any here
        return intent_text, [], []
    if not isinstance(parsed, dict):
        return intent_text, [], []

    filters = parsed.get("filters")
    if not isinstance(filters, dict):
        return intent_text, [], []

    try:
        import duckdb
        con = duckdb.connect(db_path, read_only=True)
    except Exception as e:                      # noqa: BLE001 - see docstring
        logger.warning("names: not resolved (%s)", e)
        return intent_text, [], []

    notes, unplaced, seen = [], [], {}

    def place(mention, how):
        """The extract's spelling of one mention, resolved at most once."""
        if not isinstance(mention, str) or not mention.strip():
            return mention
        key = (mention, how)
        if key not in seen:
            found, note = _resolve_one(con, mention, how)
            seen[key] = found
            if note:
                notes.append(note)
            if found is None:
                unplaced.append(mention)
        return seen[key] if seen[key] is not None else mention

    try:
        if filters.get("name"):
            filters["name"] = place(filters["name"], BY_TITLE)

        for key in ("time_constraint", "related_entity"):
            slot = filters.get(key)
            if isinstance(slot, dict) and slot.get("entity_mention"):
                slot["entity_mention"] = place(slot["entity_mention"], BY_WORD)

        compare = filters.get("compare_entities")
        if isinstance(compare, dict) and isinstance(compare.get("entities"), list):
            compare["entities"] = [place(e, BY_WORD) for e in compare["entities"]]
    finally:
        con.close()

    if not notes:
        return intent_text, [], []
    return json.dumps(parsed, indent=2, ensure_ascii=False), notes, unplaced


def _self_check(db_path: str) -> int:
    """Resolve a spread of mentions, including the ones that must not move."""
    def intent(**filters):
        base = {"name": None, "occupation": None, "location": None, "domain": None,
                "subject": None, "time_constraint": None, "related_entity": None,
                "compare_entities": None}
        base.update(filters)
        return json.dumps({"target_type": "person", "answer_field": None,
                           "filters": base})

    anchor = lambda who: {"type": "relative_to_entity", "relation": "overlap",
                          "entity_mention": who}
    #(title, intent, the name that has to come out, where to look for it)
    cases = [
        ("a misspelled anchor is read as the person meant",
         intent(occupation="physician", location="England", time_constraint=anchor("Issak Newton")),
         "Isaac Newton", ("filters", "time_constraint", "entity_mention")),
        #A typo can collide with a real name, and then it is not a typo any
        #more. "Issac Newton" is a Portuguese botanist, Q5920600, 1840-1906,
        #three sitelinks - so the name is spelled the way the extract spells
        #it and this layer leaves it alone, even though a reader almost
        #certainly meant the other one. Deciding otherwise means comparing
        #how well known the two are, which costs the 8s lookup on every
        #question, and the answer already says "Against Issac Newton
        #(1840-1906)" - the anchor prints its dates precisely so that the
        #reader can see which of the two answered.
        ("a typo that is somebody's actual name is left alone",
         intent(time_constraint=anchor("Issac Newton")),
         "Issac Newton", ("filters", "time_constraint", "entity_mention")),
        ("a correct name is left exactly as it arrived",
         intent(time_constraint=anchor("Isaac Newton")),
         "Isaac Newton", ("filters", "time_constraint", "entity_mention")),
        ("a one-word anchor, which is the shape the corpus uses",
         intent(time_constraint=anchor("Beethowen")),
         "Ludwig van Beethoven", ("filters", "time_constraint", "entity_mention")),
        ("a misspelled name filter",
         intent(name="Issak Newton"),
         "Isaac Newton", ("filters", "name")),
        ("a misspelled entity in a comparison",
         intent(compare_entities={"entities": ["Beethowen", "Mahler"],
                                  "aspect": "age", "relation": "more"}),
         "Ludwig van Beethoven", ("filters", "compare_entities", "entities", 0)),
        ("the correctly spelled half of a comparison does not move",
         intent(compare_entities={"entities": ["Beethowen", "Mahler"],
                                  "aspect": "age", "relation": "more"}),
         "Mahler", ("filters", "compare_entities", "entities", 1)),
        ("a work title keeps its wildcards",
         intent(name="Symphony 5"), "Symphony 5", ("filters", "name")),
        ("a name nobody carries is reported, not invented",
         intent(time_constraint=anchor("Xqzzy Vlurn")),
         "Xqzzy Vlurn", ("filters", "time_constraint", "entity_mention")),
    ]

    failures = 0
    for title, text, want, path in cases:
        resolved, notes, unplaced = resolve(text, db_path)
        value = json.loads(resolved)
        for step in path:
            value = value[step]
        if value != want:
            print(f"FAIL {title}: {value!r}, wanted {want!r}")
            failures += 1
            continue
        said = f" ({'; '.join(notes)})" if notes else ""
        print(f"ok   {title}: {value!r}{said}")

    #the last case has to be reported as unplaced, not silently passed through
    _, _, unplaced = resolve(intent(time_constraint=anchor("Xqzzy Vlurn")), db_path)
    if not unplaced:
        print("FAIL a name nobody carries is not reported as unplaced")
        failures += 1
    else:
        print(f"ok   an unplaceable name is reported: {unplaced}")

    #and a reply that is not an intent must come back untouched
    for junk in ("not json at all", "[1, 2, 3]", '{"filters": null}'):
        out, notes, unplaced = resolve(junk, db_path)
        if (out, notes, unplaced) != (junk, [], []):
            print(f"FAIL junk intent {junk!r} was not passed through")
            failures += 1
    print("ok   a reply that is not an intent is passed through untouched")

    print("\nall checks passed" if not failures else f"\n{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys
    db = "/home/denis/projects/wiki_data/run7/wiki.duckdb"
    args = sys.argv[1:]
    if args and args[0] == "--db":
        db = args[1]
    sys.exit(_self_check(db))
