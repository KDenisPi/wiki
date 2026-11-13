#!/usr/bin/env python3
"""Put back the leader or ruler's title, and its country, when stage 1 drops them.

The composer knows what "leaders" means - a group of offices and standings,
OCCUPATION_GROUPS in intent_to_sql.py - but only if the word reaches it.
llama3.1:8b does not reliably pass it on. Asked "Show me country leaders
(France) when Michel de Montaigne was alive?" it returned occupation null, and
asked "Who were the rulers of France when Michel de Montaigne was alive?" it
dropped the country as well. Both ran, and both answered a different
question: 200+ people alive at the same time as Montaigne, in France or
anywhere, where the right answer starts with the six kings who reigned while
he lived. The stage 1 prompt already says that "leader" is an occupation and
that "Russia leaders" has a location; the model still drops them.

So the words are read off the sentence here, after stage 1, and only to fill
a field stage 1 left empty - nothing it did fill is overwritten. Only the
composer's own words count: the leader group's, and the rulers' titles it
reads off a held office (TITLE_OFFICES - "Show me France kings when Michel de
Montaigne was alive?" lost "kings" the same way). A word the composer would
match literally gains nothing from being put back.

Two kinds of sentence look like this one and must not be filled:

  - a qualified leader. "Military leaders", "religious leaders", "party
    leaders", "drag queens", "university presidents" are a different
    question, and filling the plain word would answer it with kings. The
    words before the leader word are checked against QUALIFIERS.
  - a title inside a name. "Who lived at the same time as Martin Luther
    King?" holds "king" in the time anchor, and the composer would look for
    kings; a word inside one of the intent's names is not read.
  - the leader of something that is not a country. "The leader of the
    Beatles" names the Beatles, and stage 1 puts them in the intent as a
    named entity. A place after the leader word that is already one of the
    intent's names is taken as that, and nothing is filled - except the time
    anchor: "leaders of Montaigne's time" are a country's leaders, so the
    occupation is filled and Montaigne is not made a location.

The country is taken from the words right after the leader word - "rulers of
France", "leaders in Russia", "country leaders (France)" - and only when they
are capitalised, which is what separates "rulers of France" from "rulers of
the 16th century". A nationality adjective ("French kings") is left to stage
1, which reads those reliably, and a lowercase country to the stage 1 answer.

    python leader_words.py          # self-check, no model and no database
"""

import json
import re
import sys

from intent_to_sql import LEADER_OCCUPATIONS, OCCUPATION_GROUPS, TITLE_OFFICES

#The sentence words the composer turns into the leader group or reads as a
#ruler's title, longest first so that "country leaders" wins over "leaders"
#and "prime ministers" over nothing.
LEADER_WORDS = sorted({word for word, group in OCCUPATION_GROUPS.items()
                       if group is LEADER_OCCUPATIONS} | set(TITLE_OFFICES),
                      key=len, reverse=True)
LEADER_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in LEADER_WORDS) + r")\b",
                       re.IGNORECASE)

#A word in front of the leader word that makes it someone else's leader.
QUALIFIERS = re.compile(
    r"\b(military|army|war|religious|spiritual|church|labou?r|trade|union|party|"
    r"opposition|rebel|guerrilla|resistance|team|band|business|corporate|"
    r"community|student|youth|tribal|civil rights|movement|cult|gang|squad|"
    r"expedition|drag|beauty|prom|homecoming|carnival|race|university|college|"
    r"company|club|bank|board|academy|society)\s+$", re.IGNORECASE)

#The place right after the leader word: "(France)", or "of / in / from
#[the] France", a run of capitalised words that may hold "of" inside it
#("United States of America"). It stops at a possessive, so "leaders of
#Montaigne's time" offers "Montaigne", which is the anchor and is refused.
_CAP = r"[A-Z][\wÀ-ɏ'’-]*?"
PLACE_RE = re.compile(
    r"\s*\(\s*(?P<paren>[A-Z][^()]*?)\s*\)"
    r"|\s+(?:of|in|from)\s+(?:the\s+)?"
    rf"(?P<after>{_CAP}(?:\s+(?:of\s+(?:the\s+)?)?{_CAP})*)(?=['’]s\b|[^\w'’]|$)")


def _mentions(filters: dict) -> tuple:
    """The names the intent already holds, lowercased: these are entities, not
    places, whatever a sentence puts in front of them. The time anchor comes
    back apart from the rest - "leaders of Montaigne's time" are still a
    country's leaders, only not of a country called Montaigne, while the leader
    of a named group is not a country's leader at all."""
    def clean(values):
        return [m.lower() for m in values if isinstance(m, str) and m.strip()]
    anchor = filters.get("time_constraint")
    anchor = clean([anchor.get("entity_mention")] if isinstance(anchor, dict) else [])
    others = [filters.get("name")]
    related = filters.get("related_entity")
    if isinstance(related, dict):
        others.append(related.get("entity_mention"))
    compare = filters.get("compare_entities")
    if isinstance(compare, dict) and isinstance(compare.get("entities"), list):
        others.extend(compare["entities"])
    return anchor, clean(others)


def _is_mention(place: str, mentions: list) -> bool:
    place = place.lower()
    return any(place in m or m in place for m in mentions)


def fill(intent_text: str, sentence: str) -> tuple:
    """Fill occupation and location from the sentence's leader words.

    Returns (intent_text, notes). The intent comes back unchanged, as the same
    string, when there is nothing to fill or it is not an intent at all - the
    composer reports a broken intent better than anything here could.
    """
    try:
        intent = json.loads(intent_text)
    except (json.JSONDecodeError, TypeError):
        return intent_text, []
    if not isinstance(intent, dict) or not isinstance(intent.get("filters"), dict):
        return intent_text, []
    filters = intent["filters"]
    #a named person is the answer itself, and the leader word describes them
    if intent.get("target_type") != "person" or filters.get("name"):
        return intent_text, []
    if filters.get("occupation") and filters.get("location"):
        return intent_text, []

    notes = []
    anchor, others = _mentions(filters)
    lowered = sentence.lower()
    inside_names = [(at, at + len(m)) for m in anchor + others
                    for at in (i.start() for i in re.finditer(re.escape(m), lowered))]
    for match in LEADER_RE.finditer(sentence):
        if QUALIFIERS.search(sentence[:match.start()]):
            continue
        if any(start <= match.start() and match.end() <= end for start, end in inside_names):
            continue
        place_match = PLACE_RE.match(sentence, match.end())
        place = None
        if place_match:
            place = (place_match.group("paren") or place_match.group("after")).strip()
            if _is_mention(place, others):
                #"the leader of the Beatles": the leader word belongs to a
                #named entity, so it is not a country's leader at all
                return intent_text, []
            if _is_mention(place, anchor):
                place = None
        word = match.group(1).lower()
        if not filters.get("occupation"):
            filters["occupation"] = word
            notes.append(f"occupation {word!r} read from the sentence - stage 1 left it empty")
        if place and not filters.get("location"):
            filters["location"] = place
            notes.append(f"location {place!r} read from the sentence - stage 1 left it empty")
        break

    if not notes:
        return intent_text, []
    return json.dumps(intent, indent=2, ensure_ascii=False), notes


def _self_check() -> int:
    """Sentences and what each must fill; no model and no database needed."""
    def intent(occupation=None, location=None, name=None, anchor=None, related=None,
               target="person"):
        return json.dumps({"target_type": target, "answer_field": None, "filters": {
            "name": name, "occupation": occupation, "subject": None, "location": location,
            "domain": None,
            "time_constraint": ({"type": "relative_to_entity", "relation": "overlap",
                                 "entity_mention": anchor} if anchor else None),
            "related_entity": ({"relation": "participates_in", "entity_mention": related}
                               if related else None),
            "compare_entities": None}})

    montaigne = "Michel de Montaigne"
    cases = [
        #(sentence, stage 1's intent, occupation and location afterwards)
        ("Show me country leaders (France) when Michel de Montaigne was alive?",
         intent(location="France", anchor=montaigne), ("country leaders", "France")),
        ("Who were the rulers of France when Michel de Montaigne was alive?",
         intent(anchor=montaigne), ("rulers", "France")),
        ("leaders in Russia in the 16th century", intent(), ("leaders", "Russia")),
        ("Which heads of state of the United States of America lived after Lincoln?",
         intent(anchor="Lincoln"), ("heads of state", "United States of America")),
        ("rulers of the 16th century", intent(), ("rulers", None)),
        ("Who were the leaders of Montaigne's time?", intent(anchor="Montaigne"),
         ("leaders", None)),
        #stage 1 did its job: nothing is touched
        ("Which French kings ruled after Montaigne?",
         intent(occupation="king", location="France", anchor="Montaigne"), ("king", "France")),
        ("Who were the rulers of France?", intent(occupation="ruler", location="France"),
         ("ruler", "France")),
        #only the empty field is filled
        ("Who were the rulers of France?", intent(occupation="monarch"),
         ("monarch", "France")),
        #someone else's leaders
        ("Which military leaders lived in France?", intent(location="France"),
         (None, "France")),
        ("religious leaders of Tibet", intent(), (None, None)),
        ("Who was the leader of the Beatles?", intent(related="the Beatles"), (None, None)),
        #a named target is described by the word, not filtered by it
        ("Was Napoleon a ruler of France?", intent(name="Napoleon"), (None, None)),
        ("Which wars did rulers of France fight?", intent(target="event"), (None, None)),
        #a ruler's title, read the same way
        ("Show me the French kings when Michel de Montaigne was alive?",
         intent(location="France", anchor=montaigne), ("kings", "France")),
        ("Who were the kings of Spain in the 16th century?", intent(), ("kings", "Spain")),
        ("List the prime ministers of the United Kingdom", intent(),
         ("prime ministers", "United Kingdom")),
        ("Which drag queens lived in Paris?", intent(location="Paris"), (None, "Paris")),
        ("List university presidents in France", intent(location="France"), (None, "France")),
        ("Who lived at the same time as Martin Luther King?",
         intent(anchor="Martin Luther King"), (None, None)),
        #not an intent
        ("rulers of France", "not json", None),
    ]
    failures = 0
    for sentence, given, want in cases:
        text, notes = fill(given, sentence)
        if want is None:
            ok = text == given and not notes
            got = "unchanged" if ok else text
        else:
            filters = json.loads(text)["filters"]
            got = (filters["occupation"], filters["location"])
            ok = got == want
        print(f"{'ok  ' if ok else 'FAIL'} {sentence!r}: {got}" + (f"  [{'; '.join(notes)}]" if notes else ""))
        failures += not ok
    print("\nall checks passed" if not failures else f"\n{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_self_check())
