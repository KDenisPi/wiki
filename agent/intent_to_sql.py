#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build DuckDB SQL from a stage-1 intent, deterministically.

Stage 2 used to be a second model asked to turn the intent JSON into SQL. It
kept producing queries that ran and returned rows while quietly answering a
different question: the creator name dropped and replaced with
"a.property IS NOT NULL", a subject regex applied to the creator's alias, a
domain filter invented as attributes.value IN ('literature','fiction') when
that column holds QIDs. Valid SQL, plausible output, wrong answer - the worst
failure mode available, because nothing raises.

Every filter here is one fixed pattern, taken from the queries in queries.sql
that were checked against the database by hand. A filter cannot be dropped,
softened or aimed at the wrong column, because it is a line of Python rather
than a suggestion to a 7B model.

Filters are EXISTS subqueries, not joins. An item usually has several rows per
attribute (three occupations, two citizenships), so joining one pair of tables
per filter multiplies rows and forces a GROUP BY to undo the damage, and two
filters sharing one join pair silently ask a single attribute row to satisfy
both conditions at once. EXISTS asks the question each filter actually means -
"is there such a row" - independently of every other filter.

Anything the composer cannot express raises Unsupported, so the caller can fall
back to the model rather than get a confidently wrong query.

    >>> from intent_to_sql import build_sql
    >>> build_sql({"target_type": "work", "answer_field": None,
    ...            "filters": {"related_entity": {"relation": "creates",
    ...                                           "entity_mention": "Isaac Newton"}}})

Self-check (builds SQL for a set of intents and runs each one):
    python intent_to_sql.py --db /home/denis/projects/wiki_data/run2/wiki.duckdb
"""

import json
import re
import sys

#The seven tags in classes.domains, one per seed group in build_class_closure.py.
#Anything else matches no row at all, so it is dropped rather than applied.
DOMAINS = ("art", "event", "literature", "music", "person", "place", "science")

#Who made a work. Which one a work uses is not predictable - a book is P50, a
#symphony P86, a painting P170 - so they are always tested together.
CREATOR_PROPS = ("P50", "P86", "P170", "P175", "P676")

#Where an item is, by what the place means for that kind of item. Filtering is
#deliberately broad - "scientists in Germany" should accept citizenship or
#birthplace or where they worked.
PLACE_PROPS = {
    "person": ("P27", "P19", "P20", "P937"),   # citizenship, birth, death, work
    "work":   ("P17", "P276"),                 # country, location
    "event":  ("P17", "P276"),
}

#Answering "where" is the opposite case: it needs the one place the question
#asked for. Reporting all four for a person turns "where was Einstein born"
#into "Weimar Republic, Germany, Caputh, United States, ... , Ulm".
ANSWER_PLACE_PROPS = {
    "person": ("P19",),                        # place of birth
    "work":   ("P17", "P276"),
    "event":  ("P17", "P276"),
}

#"label" is quoted because DuckDB treats it as a keyword in some positions.
#They are names rather than inline strings so that f-strings below stay free of
#backslashes, which Python 3.11 rejects inside an expression part.
I_LABEL = 'i."label"'
V_LABEL = 'v."label"'
W_LABEL = 'w."label"'

OCCUPATION_PROP = "P106"

#An occupation word that names a whole area rather than a profession. Matching
#those literally answers nothing useful: the 15th century holds 58,088 dated
#people, but only 50 of them are labelled "scientist" - the rest are
#astronomers, physicians and mathematicians. occupation_areas maps every
#profession in the extract onto these four (build_occupation_areas.py), so the
#area word becomes a lookup instead of a string comparison.
OCCUPATION_AREAS = {
    "science": "science", "scientist": "science", "scientists": "science",
    "researcher": "science", "researchers": "science",
    "music": "music", "musician": "music", "musicians": "music",
    "art": "art", "artist": "art", "artists": "art",
    "literature": "literature", "writer": "literature", "writers": "literature",
    "author": "literature", "authors": "literature",
}
SUBJECT_PROPS = ("P921", "P101", "P136")       # main subject, field of work, genre
PARTICIPANT_PROPS = ("P710", "P1344")          # participant, participant in
BIRTH, DEATH = "P569", "P570"

#A death year more than this after the birth year is a data error, not a life.
MAX_LIFESPAN = 110

TARGET_TYPES = ("person", "work", "event")


class Unsupported(Exception):
    """The intent has a shape the composer does not cover."""


def _lit(value: str) -> str:
    """A SQL string literal. Doubling the quote is the whole escape rule."""
    return "'" + str(value).replace("'", "''") + "'"


def _word_match(column: str, value: str) -> str:
    """Match a name against a label on word boundaries.

    Equality is too strict - the anchor "Beethoven" has to find "Ludwig van
    Beethoven", and "physics" has to find "classical physics". ILIKE '%x%' is
    too loose - "Russia" would take "Prussia" and "Byelorussia" with it. The
    word boundary keeps the first and rejects the second.
    """
    pattern = "(?i)\\b" + re.escape(value)
    return f"regexp_matches({column}, {_lit(pattern)})"


def _title_match(column: str, value: str) -> str:
    """Match a work title, where the sentence rarely has it exactly right.

    "Symphony 5" has to reach the stored "Symphony No. 5", so the internal
    spaces become wildcards.
    """
    pattern = "%" + "%".join(value.split()) + "%"
    return f"{column} ILIKE {_lit(pattern)}"


def _fuzzy_match(column: str, value: str) -> str:
    """Match a name the sentence spells wrong.

    Stage 1 preserves the question's spelling on purpose, typos included, so
    "Beethowen" arrives as written and no exact or word-boundary match will
    ever find "Ludwig van Beethoven". Each word of the mention has to be close
    to some word of the label; whole-label similarity does not work, because
    "Beethowen" against "Ludwig van Beethoven" scores low on length alone.
    """
    parts = [f"len(list_filter(str_split({column}, ' '),"
             f" w -> jaro_winkler_similarity(w, {_lit(word)}) >= 0.9)) > 0"
             for word in value.split()]
    return "(" + " AND ".join(parts) + ")"


def _name_match(column: str, value: str) -> str:
    """A named entity: correct spelling first, misspelling second."""
    return f"({_word_match(column, value)} OR {_fuzzy_match(column, value)})"


def _occupation_area_exists(area: str) -> str:
    """Does this person hold any occupation belonging to the area."""
    return (f"EXISTS (SELECT 1 FROM attributes a"
            f" JOIN occupation_areas oa ON oa.qid = a.\"value\""
            f" WHERE a.qid = i.qid AND a.property = {_lit(OCCUPATION_PROP)}"
            f" AND list_contains(str_split(oa.areas, '|'), {_lit(area)}))")


def _attribute_exists(props, match: str) -> str:
    """One attribute filter: is there a row of these properties whose value
    label matches. `match` is an expression over the alias `v`."""
    plist = ", ".join(_lit(p) for p in props)
    return (f"EXISTS (SELECT 1 FROM attributes a"
            f" JOIN value_items v ON v.qid = a.\"value\""
            f" WHERE a.qid = i.qid AND a.property IN ({plist})"
            f" AND {match})")


def _year_expr(prop: str = None) -> str:
    """The item's year, as a scalar subquery so it needs no join and cannot
    multiply rows.

    Named property (a person's birth or death): max, to settle the handful of
    items carrying two conflicting values, matching query 3 in queries.sql.
    Any property (a work or an event): min, because a work usually has several
    dates - inception 1680 and publication 1687 for the Principia - and the
    question "works created in the 18th century" means the earliest of them.
    """
    if prop:
        return (f"(SELECT max(e.year) FROM events e"
                f" WHERE e.qid = i.qid AND e.property = {_lit(prop)})")
    return "(SELECT min(e.year) FROM events e WHERE e.qid = i.qid)"


def _anchor_cte(mention: str) -> str:
    """The lifespan of one named person, used as a time anchor.

    Many items share a surname, so the anchor is resolved to a person who has a
    birth date and is the most documented of the candidates - never LIMIT 1 on
    the bare label, which picks an arbitrary namesake.
    """
    return f"""anchor AS (
    SELECT {_year_expr(BIRTH)} AS born,
           {_year_expr(DEATH)} AS died
    FROM items i
    WHERE {_word_match('coalesce(i."label", i.label_ru)', mention)}
      AND {_year_expr(BIRTH)} IS NOT NULL
    ORDER BY (SELECT count(*) FROM attributes a WHERE a.qid = i.qid) DESC
    LIMIT 1
)"""


def _person_cte(name: str, mention: str) -> str:
    """Resolve one named person to a single row of the facts comparisons need.

    The same disambiguation as the time anchor: a person, with a birth date,
    and the best known of the candidates - the fuzzy name match is deliberately
    loose enough to reach a misspelling, so it also reaches noise, and
    sitelinks is what separates Ludwig van Beethoven from a clinical trial
    whose title happens to contain a similar word.
    """
    creators = ", ".join(_lit(p) for p in CREATOR_PROPS)
    return f"""{name} AS (
    SELECT coalesce(i."label", i.label_ru) AS name,
           {_year_expr(BIRTH)} AS born,
           {_year_expr(DEATH)} AS died,
           (SELECT count(DISTINCT a.qid) FROM attributes a
             WHERE a."value" = i.qid AND a.property IN ({creators})) AS works,
           (SELECT string_agg(DISTINCT {V_LABEL}, ', ') FROM attributes a
             JOIN value_items v ON v.qid = a."value"
             WHERE a.qid = i.qid AND a.property = {_lit('P27')}) AS country
    FROM items i
    WHERE EXISTS (SELECT 1 FROM item_classes l JOIN classes c ON c.qid = l."class"
                  WHERE l.qid = i.qid AND c.domains LIKE {_lit('%person%')})
      AND {_name_match('coalesce(i."label", i.label_ru)', mention)}
      AND {_year_expr(BIRTH)} IS NOT NULL
    ORDER BY (SELECT sitelinks FROM sites s WHERE s.qid = i.qid) DESC NULLS LAST
    LIMIT 1
)"""


def _compare_query(compare: dict) -> str:
    """Compare two named people directly - who lived longer, who wrote more.

    A different shape from every other question here: not a list of items
    filtered down, but one row holding both entities' facts and the answer.
    """
    entities = compare.get("entities") or []
    if len(entities) != 2:
        raise Unsupported(f"compare_entities with {len(entities)} entities")

    aspect = compare.get("aspect")
    relation = compare.get("relation")
    ctes = [_person_cte("e1", entities[0]), _person_cte("e2", entities[1])]

    #a death year missing or absurd would make any of these comparisons lie
    sane = (f"e1.died IS NOT NULL AND e2.died IS NOT NULL"
            f" AND e1.died - e1.born BETWEEN 0 AND {MAX_LIFESPAN}"
            f" AND e2.died - e2.born BETWEEN 0 AND {MAX_LIFESPAN}")

    if aspect == "time":
        answers = {
            "overlap": "e1.born <= e2.died AND e1.died >= e2.born",
            "before":  "e1.died <= e2.born",
            "after":   "e1.born >= e2.died",
        }
        if relation not in answers:
            raise Unsupported(f"time comparison {relation!r}")
        columns = ["e1.born AS born_1", "e1.died AS died_1",
                   "e2.born AS born_2", "e2.died AS died_2"]
        answer = f"CASE WHEN {sane} THEN ({answers[relation]}) END"

    elif aspect == "age":
        columns = ["e1.died - e1.born AS age_1", "e2.died - e2.born AS age_2"]
        comparison = {"more": ">", "fewer": "<", "equal": "="}.get(relation)
        if comparison is None:
            raise Unsupported(f"age comparison {relation!r}")
        answer = (f"CASE WHEN {sane} THEN"
                  f" ((e1.died - e1.born) {comparison} (e2.died - e2.born)) END")

    elif aspect == "work_count":
        columns = ["e1.works AS works_1", "e2.works AS works_2"]
        comparison = {"more": ">", "fewer": "<", "equal": "="}.get(relation)
        if comparison is None:
            raise Unsupported(f"work_count comparison {relation!r}")
        #work_type would need the class closure per work; counting every work
        #either created is the honest approximation, so it is not applied
        answer = f"e1.works {comparison} e2.works"

    elif aspect == "location":
        columns = ["e1.country AS country_1", "e2.country AS country_2"]
        if relation not in ("same", "different"):
            raise Unsupported(f"location comparison {relation!r}")
        overlap = ("len(list_intersect(str_split(e1.country, ', '),"
                   " str_split(e2.country, ', '))) > 0")
        answer = overlap if relation == "same" else f"NOT ({overlap})"

    else:
        raise Unsupported(f"compare aspect {aspect!r}")

    select = ["e1.name AS entity_1", "e2.name AS entity_2"] + columns + [f"({answer}) AS answer"]
    return ("WITH " + ",\n".join(ctes) + "\n"
            + "SELECT " + ",\n       ".join(select) + "\nFROM e1, e2;")


def _time_conditions(target: str, constraint: dict, ctes: list) -> list:
    """Turn a time_constraint into conditions on the target's dates."""
    kind = constraint.get("type")

    if kind == "in_range":
        start, end = constraint.get("start_year"), constraint.get("end_year")
        if start is None or end is None:
            raise Unsupported("in_range without both years")
        if target == "person":
            #"lived in the 1400s" is read as born or died inside the window,
            #which also keeps people whose other date is unknown.
            return [f"EXISTS (SELECT 1 FROM events e WHERE e.qid = i.qid"
                    f" AND e.property IN ({_lit(BIRTH)}, {_lit(DEATH)})"
                    f" AND e.year BETWEEN {int(start)} AND {int(end)})"]
        return [f"EXISTS (SELECT 1 FROM events e WHERE e.qid = i.qid"
                f" AND e.year BETWEEN {int(start)} AND {int(end)})"]

    if kind == "relative_to_entity":
        mention = constraint.get("entity_mention")
        relation = constraint.get("relation")
        if not mention or relation not in ("overlap", "before", "after"):
            raise Unsupported(f"relative_to_entity {relation!r}")
        ctes.append(_anchor_cte(mention))
        born, died = _year_expr(BIRTH), _year_expr(DEATH)
        conditions = [f"{born} IS NOT NULL",
                      f"coalesce({died} - {born}, 0) <= {MAX_LIFESPAN}"]
        if relation == "overlap":
            conditions += [f"{born} <= (SELECT died FROM anchor)",
                           f"coalesce({died}, {born}) >= (SELECT born FROM anchor)"]
        elif relation == "before":
            conditions += [f"coalesce({died}, {born}) <= (SELECT born FROM anchor)"]
        else:
            conditions += [f"{born} >= (SELECT died FROM anchor)"]
        return conditions

    raise Unsupported(f"time_constraint type {kind!r}")


def _related_conditions(target: str, related: dict) -> list:
    """A named entity the target is linked to."""
    relation = related.get("relation")
    mention = related.get("entity_mention")
    if not mention:
        raise Unsupported("related_entity without entity_mention")

    if relation == "creates":
        if target == "work":
            #the named person made this work
            return [_attribute_exists(CREATOR_PROPS, _word_match(V_LABEL, mention))]
        if target == "person":
            #this person made the named work: the attribute row sits on the
            #work and points back at the person
            plist = ", ".join(_lit(p) for p in CREATOR_PROPS)
            return [f"EXISTS (SELECT 1 FROM attributes a"
                    f" JOIN items w ON w.qid = a.qid"
                    f" WHERE a.\"value\" = i.qid AND a.property IN ({plist})"
                    f" AND {_title_match(W_LABEL, mention)})"]
        raise Unsupported(f"creates with target {target!r}")

    if relation == "participates_in":
        #recorded from either side, so both directions are checked
        return [f"({_attribute_exists(PARTICIPANT_PROPS, _word_match(V_LABEL, mention))}"
                f" OR EXISTS (SELECT 1 FROM attributes a JOIN items w ON w.qid = a.qid"
                f" WHERE a.\"value\" = i.qid AND a.property IN ({_lit('P710')}, {_lit('P1344')})"
                f" AND {_title_match(W_LABEL, mention)}))"]

    if relation == "located_in":
        return [_attribute_exists(PLACE_PROPS[target], _word_match(V_LABEL, mention))]

    raise Unsupported(f"relation {relation!r}")


def build_sql(intent: dict, limit: int = 200) -> str:
    """Compose one DuckDB SELECT for a stage-1 intent.

    Raises Unsupported for shapes not covered, so the caller can fall back to
    the model instead of running a query that answers the wrong question.
    """
    if not isinstance(intent, dict):
        raise Unsupported("intent is not an object")

    target = intent.get("target_type")
    if target not in TARGET_TYPES:
        raise Unsupported(f"target_type {target!r}")

    filters = intent.get("filters") or {}
    if filters.get("compare_entities"):
        #a comparison answers with one row about two entities, not a filtered
        #list, so it is built separately and returned whole
        return _compare_query(filters["compare_entities"])

    answer_field = intent.get("answer_field")
    if answer_field not in (None, "time", "location"):
        raise Unsupported(f"answer_field {answer_field!r}")

    ctes, where = [], []
    dropped = []
    #an area can arrive twice - "which scientists" often sets both occupation
    #and domain - and the same EXISTS twice only costs time
    areas_applied = set()

    if target == "person":
        #A "person" question must come back with people. Without this, a name
        #match on "Albert Einstein" also finds the quotation item labelled
        #"'Not everything that can be counted counts...' (attributed to Albert
        #Einstein)", which has no birthplace and sorts first alphabetically.
        where.append(f"EXISTS (SELECT 1 FROM item_classes l"
                     f" JOIN classes c ON c.qid = l.\"class\""
                     f" WHERE l.qid = i.qid AND c.domains LIKE {_lit('%person%')})")

    if filters.get("name"):
        name = filters["name"]
        where.append(f"({_title_match(I_LABEL, name)}"
                     f" OR {_title_match('i.label_ru', name)})")

    if filters.get("occupation"):
        #an occupation is a value in the P106 vocabulary, never a word in the
        #item's own label
        occupation = str(filters["occupation"]).strip().lower()
        area = OCCUPATION_AREAS.get(occupation)
        if area:
            #"scientists" is 2,039 professions, not one label
            where.append(_occupation_area_exists(area))
            areas_applied.add(area)
        else:
            where.append(_attribute_exists((OCCUPATION_PROP,),
                                           _word_match(V_LABEL, filters['occupation'])))

    if filters.get("location"):
        where.append(_attribute_exists(PLACE_PROPS[target],
                                       _word_match(V_LABEL, filters['location'])))

    if filters.get("domain"):
        domain = str(filters["domain"]).lower()
        if target == "person" and domain in OCCUPATION_AREAS:
            #A person's class tag is "person" - never science or music, which
            #describe what a work IS. For someone, the area is carried by their
            #occupation, so "scientists in Germany" sends domain there too;
            #applied to classes.domains it would match nobody at all.
            area = OCCUPATION_AREAS[domain]
            if area not in areas_applied:
                where.append(_occupation_area_exists(area))
                areas_applied.add(area)
        elif domain in DOMAINS:
            where.append(f"EXISTS (SELECT 1 FROM item_classes l"
                         f" JOIN classes c ON c.qid = l.\"class\""
                         f" WHERE l.qid = i.qid AND c.domains LIKE {_lit('%' + domain + '%')})")
        else:
            #a tag outside the seven matches nothing, so applying it would
            #empty the answer instead of narrowing it
            dropped.append(f"domain {domain!r} is not one of {', '.join(DOMAINS)}")

    if filters.get("subject"):
        #what the item is about, which lives in attributes - classes.domains
        #records what it IS (Newton's books are all tagged literature)
        where.append(_attribute_exists(SUBJECT_PROPS,
                                       _word_match(V_LABEL, filters['subject'])))

    if filters.get("related_entity"):
        where += _related_conditions(target, filters["related_entity"])

    if filters.get("time_constraint"):
        where += _time_conditions(target, filters["time_constraint"], ctes)

    if not where:
        raise Unsupported("no filters to constrain the query")

    label = 'coalesce(i."label", i.label_ru)'
    place_props = ", ".join(_lit(p) for p in ANSWER_PLACE_PROPS[target])
    places = (f"(SELECT string_agg(DISTINCT {V_LABEL}, ', ') FROM attributes a"
              f" JOIN value_items v ON v.qid = a.\"value\""
              f" WHERE a.qid = i.qid AND a.property IN ({place_props}))")

    sitelinks = "(SELECT sitelinks FROM sites s WHERE s.qid = i.qid)"

    if answer_field == "location":
        select = [f"{label} AS {target}", f"{places} AS location"]
        order = ""
    elif target == "person":
        select = [f"{label} AS person",
                  f"{_year_expr(BIRTH)} AS born",
                  f"{_year_expr(DEATH)} AS died"]
        order = "born NULLS LAST"
    else:
        #Show the date the question asked about. A work often carries several
        #dates, and the filter only requires one of them to fall in the window,
        #so projecting the earliest of all of them lists a 15th-century carol
        #under "musical works of the 18th century" - the row matches, the year
        #printed next to it does not.
        constraint = filters.get("time_constraint") or {}
        if constraint.get("type") == "in_range":
            year = (f"(SELECT min(e.year) FROM events e WHERE e.qid = i.qid"
                    f" AND e.year BETWEEN {int(constraint['start_year'])}"
                    f" AND {int(constraint['end_year'])})")
        else:
            year = _year_expr()
        select = [f"{label} AS {target}", f"{year} AS year"]
        order = "year NULLS LAST"

    #The sitelink count is the only ranking signal the dump offers. A question
    #naming an entity wants that entity, so notability leads the ordering: 21
    #items are labelled "Symphony No. 9" and several hundred contain "Albert
    #Einstein". Listing questions stay in date order with notability as the
    #tie-break.
    select.append(f"{sitelinks} AS sitelinks")
    lead = "sitelinks DESC NULLS LAST"
    order = lead if (filters.get("name") or not order) else f"{order}, {lead}"

    sql = ""
    if ctes:
        sql += "WITH " + ",\n".join(ctes) + "\n"
    sql += ("SELECT " + ",\n       ".join(select)
            + "\nFROM items i\nWHERE " + "\n  AND ".join(where)
            + f"\nORDER BY {order}\nLIMIT {int(limit)};")

    if dropped:
        sql = "-- dropped: " + "; ".join(dropped) + "\n" + sql
    return sql


def _self_check(db_path: str) -> int:
    """Build SQL for a spread of intents and run each one."""
    def intent(target, answer=None, **filters):
        base = {"name": None, "occupation": None, "location": None, "domain": None,
                "subject": None, "time_constraint": None, "related_entity": None,
                "compare_entities": None}
        base.update(filters)
        return {"target_type": target, "answer_field": answer, "filters": base}

    cases = [
        ("books by Newton",
         intent("work", domain="literature",
                related_entity={"relation": "creates", "entity_mention": "Isaac Newton"})),
        ("works by Newton, no domain",
         intent("work", related_entity={"relation": "creates", "entity_mention": "Isaac Newton"})),
        ("works by Newton in mathematics",
         intent("work", subject="mathematics",
                related_entity={"relation": "creates", "entity_mention": "Isaac Newton"})),
        ("works by Newton in physics",
         intent("work", subject="physics",
                related_entity={"relation": "creates", "entity_mention": "Isaac Newton"})),
        ("musical works of the 18th century",
         intent("work", domain="music",
                time_constraint={"type": "in_range", "start_year": 1701, "end_year": 1800})),
        ("German mathematicians of the 1400s",
         intent("person", occupation="mathematician", location="Germany",
                time_constraint={"type": "in_range", "start_year": 1400, "end_year": 1499})),
        ("German scientists of the 1400s (area, not a job title)",
         intent("person", occupation="scientists", location="Germany",
                time_constraint={"type": "in_range", "start_year": 1400, "end_year": 1499})),
        ("composers before Beethoven",
         intent("person", occupation="composer",
                time_constraint={"type": "relative_to_entity", "relation": "before",
                                 "entity_mention": "Beethoven"})),
        ("where was Einstein born",
         intent("person", answer="location", name="Albert Einstein")),
        ("who lived longer, misspelled",
         intent("person", compare_entities={"entities": ["Beethowen", "Mahler"],
                                            "aspect": "age", "relation": "more"})),
        ("did they live at the same time",
         intent("person", compare_entities={"entities": ["Beethowen", "Mahler"],
                                            "aspect": "time", "relation": "overlap"})),
        ("who composed more",
         intent("person", compare_entities={"entities": ["Beethoven", "Mahler"],
                                            "aspect": "work_count", "relation": "more",
                                            "work_type": "symphony"})),
        ("born in the same country",
         intent("person", compare_entities={"entities": ["Beethoven", "Mahler"],
                                            "aspect": "location", "relation": "same"})),
        ("unknown domain is dropped, not applied",
         intent("work", domain="mathematics",
                related_entity={"relation": "creates", "entity_mention": "Isaac Newton"})),
    ]

    try:
        import duckdb
        con = duckdb.connect(db_path, read_only=True)
    except Exception as e:                      # noqa: BLE001 - report and keep going
        print(f"no database ({e}) - checking SQL generation only\n")
        con = None

    failures = 0
    for title, value in cases:
        try:
            sql = build_sql(value, limit=5)
        except Unsupported as e:
            print(f"FAIL {title}: unsupported ({e})")
            failures += 1
            continue

        if con is None:
            print(f"ok   {title}: built {len(sql)} chars")
            continue

        try:
            rows = con.execute(sql).fetchall()
        except Exception as e:                  # noqa: BLE001 - the point of the check
            print(f"FAIL {title}: {e}\n{sql}\n")
            failures += 1
            continue

        first = rows[0][0] if rows else "-"
        print(f"ok   {title}: {len(rows)} row(s), first {first!r}")

    if con is not None:
        con.close()
    print("\nall checks passed" if not failures else f"\n{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    db = "/home/denis/projects/wiki_data/run2/wiki.duckdb"
    args = sys.argv[1:]
    if args and args[0] == "--db":
        db = args[1]
        args = args[2:]
    if args:
        #an intent on stdin or as a file, printed as SQL
        print(build_sql(json.loads(open(args[0]).read())))
        sys.exit(0)
    sys.exit(_self_check(db))
