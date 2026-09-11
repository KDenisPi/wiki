"""One sentence of English for a result set, instead of a tuple.

The composer emits a small, fixed set of column shapes, and each one already
says what the question was - a comparison ends in an "answer" column, a person
list carries born/died, a work list carries a year. So the phrasing is chosen
from the columns rather than from the intent, which means it still works when
the SQL came from the model and no intent survived.

What it deliberately does not do: invent anything the row does not say. A
comparison whose answer is NULL says so rather than guessing, and a count that
is really "works in the extract" is never called an oeuvre.

    >>> describe(["entity_1", "entity_2", "born_1", "died_1", "born_2", "died_2", "answer"],
    ...          [("Ludwig van Beethoven", "Wolfgang Amadeus Mozart",
    ...            1770, 1827, 1756, 1791, True)])
    'Yes - Ludwig van Beethoven (1770-1827) and Wolfgang Amadeus Mozart (1756-1791) overlapped by 21 years.'
"""

#What to call the rows of a listing question. The column the composer names the
#target with is the singular, and only these three ever reach here.
PLURALS = {"person": "people", "work": "works", "event": "events"}

#The unit that belongs after a superlative's measure, so "65" reads as a
#lifespan and 1685 as a year rather than both as bare numbers.
UNITS = {"age": " years", "works": " works", "born": None}


def _year(year) -> str:
    """A year as a reader expects it. The dump stores BC as a negative number,
    and "the Darius Painter (b. -400)" is arithmetic, not a date."""
    if year is None:
        return "?"
    return f"{abs(year)} BC" if year < 0 else str(year)


def _life(born, died) -> str:
    """A lifespan in parentheses, honest about a missing death date."""
    if born is None:
        return "dates unknown"
    if died is None:
        #still alive, or the extract never had the date - either way the dash
        #is the claim being made, so leave it open rather than closing it
        return f"b. {_year(born)}"
    return f"{_year(born)}-{_year(died)}"


def _join(parts: list) -> str:
    """a, b and c - the serial comma left out, as English rather than SQL."""
    parts = [p for p in parts if p]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _time_phrase(n1, b1, d1, n2, b2, d2) -> str:
    """What is actually true between two lifespans.

    Said the same way whether the question asked "at the same time", "before"
    or "after": the relation found is the informative part, and the Yes/No in
    front of it already answers what was asked.
    """
    if None in (b1, b2):
        return f"{n1} ({_life(b1, d1)}) and {n2} ({_life(b2, d2)})"
    if d1 is not None and d1 < b2:
        return (f"{n1} ({_life(b1, d1)}) died {b2 - d1} years before"
                f" {n2} was born ({_life(b2, d2)})")
    if d2 is not None and d2 < b1:
        return (f"{n2} ({_life(b2, d2)}) died {b1 - d2} years before"
                f" {n1} was born ({_life(b1, d1)})")
    #they overlap; the shorter end of the overlap is whichever died first, and
    #an unknown death date cannot shorten it
    ends = [d for d in (d1, d2) if d is not None]
    overlap = min(ends) - max(b1, b2) if ends else None
    if overlap is None or overlap < 0:
        return f"{n1} ({_life(b1, d1)}) and {n2} ({_life(b2, d2)}) overlapped"
    return (f"{n1} ({_life(b1, d1)}) and {n2} ({_life(b2, d2)})"
            f" overlapped by {overlap} years")


def _compare_two(get, row) -> str:
    """A yes/no comparison of two named people."""
    verdict = get(row, "answer")
    n1, n2 = get(row, "entity_1"), get(row, "entity_2")
    said = {True: "Yes", False: "No"}.get(verdict)

    if get(row, "born_1", missing=False) is not False:
        phrase = _time_phrase(n1, get(row, "born_1"), get(row, "died_1"),
                              n2, get(row, "born_2"), get(row, "died_2"))
    elif get(row, "age_1", missing=False) is not False:
        a1, a2 = get(row, "age_1"), get(row, "age_2")
        phrase = f"{n1} lived {a1} years, {n2} {a2}"
    elif get(row, "works_1", missing=False) is not False:
        w1, w2 = get(row, "works_1") or 0, get(row, "works_2") or 0
        #"in the extract" is not padding: this counts the works this database
        #happens to hold, which is not the same as everything they wrote
        phrase = f"{n1} has {w1:,} works in the extract, {n2} {w2:,}"
    else:
        c1, c2 = get(row, "country_1"), get(row, "country_2")
        if verdict is True and c1:
            phrase = f"both from {c1}"
        else:
            #each country is itself a comma-joined list ("Salzburg, Holy Roman
            #Empire"), so the two people are split by a semicolon or the
            #sentence reads as one run-on list of places
            phrase = (f"{n1} from {c1 or 'somewhere unrecorded'};"
                      f" {n2} from {c2 or 'somewhere unrecorded'}")

    if said is None:
        #the composer returns NULL when a date is missing or absurd, and that
        #is an answer worth printing plainly instead of as "None"
        return f"Not enough in the extract to say - {phrase}."
    return f"{said} - {phrase}."


def _compare_many(columns, row) -> str:
    """Which of three or more named people wins, and by how much."""
    winner = row[columns.index("answer")]
    measure = next((c.rsplit("_", 1)[0] for c in columns
                    if c.rsplit("_", 1)[0] in UNITS), None)
    unit = UNITS.get(measure) or ""
    names = [row[i] for i, c in enumerate(columns) if c.startswith("entity_")]
    values = [row[i] for i, c in enumerate(columns)
              if measure and c.startswith(f"{measure}_")]

    pairs = list(zip(names, values))
    top = next((v for n, v in pairs if n == winner), None)
    rest = [f"{n} {v}" for n, v in pairs if n != winner and v is not None]
    if top is None:
        return f"{winner}."
    lead = f"{winner} - {top}{unit}" if unit else f"{winner} - born {top}"
    return f"{lead}, against {_join(rest)}." if rest else f"{lead}."


def _listing(columns, rows, limit=None) -> str:
    """A listing question: how many, and the first few by name."""
    target = columns[0]
    count = len(rows)
    #one row is one person, not one people
    noun = target if count == 1 else PLURALS.get(target, target + "s")
    #a result sitting exactly on the row limit was cut off, and saying "200"
    #where the truth is "at least 200" is the one number worth qualifying
    total = f"{count}+" if limit and count >= limit else f"{count}"

    shown = []
    for row in rows[:3]:
        name = row[0]
        if "born" in columns:
            detail = _life(row[columns.index("born")], row[columns.index("died")])
        elif "year" in columns:
            year = row[columns.index("year")]
            detail = _year(year) if year is not None else None
        else:
            detail = None
        shown.append(f"{name} ({detail})" if detail else str(name))

    head = _join(shown) if count <= 3 else ", ".join(shown)
    if count > 3:
        return f"{total} {noun}: {head} and {count - 3} more."
    return f"{total} {noun}: {head}."


def describe(columns, rows, limit=None):
    """One sentence for a result set, or None if the shape is unrecognised.

    None rather than a guess: the caller still logs the rows, and a wrong
    sentence about them would be worse than no sentence at all.
    """
    if not columns:
        return None
    if not rows:
        return "Nothing in the extract matches that."

    def get(row, name, missing=None):
        return row[columns.index(name)] if name in columns else missing

    if "answer" in columns and "entity_1" in columns:
        #two entities are a yes/no; three or more name the winner, and the
        #answer column's type is what tells them apart
        answer = rows[0][columns.index("answer")]
        if isinstance(answer, str):
            return _compare_many(columns, rows[0])
        return _compare_two(get, rows[0])

    if "location" in columns:
        name, place = rows[0][0], rows[0][columns.index("location")]
        if place is None:
            return f"{name} - no place recorded in the extract."
        return f"{name} - {place}."

    if columns[0] in PLURALS or "born" in columns or "year" in columns:
        return _listing(columns, rows, limit)

    return None


def _self_check() -> int:
    cases = [
        (["entity_1", "entity_2", "born_1", "died_1", "born_2", "died_2", "answer"],
         [("Ludwig van Beethoven", "Wolfgang Amadeus Mozart", 1770, 1827, 1756, 1791, True)],
         "Yes - Ludwig van Beethoven (1770-1827) and Wolfgang Amadeus Mozart"
         " (1756-1791) overlapped by 21 years."),
        (["entity_1", "entity_2", "born_1", "died_1", "born_2", "died_2", "answer"],
         [("Isaac Newton", "Albert Einstein", 1643, 1727, 1879, 1955, False)],
         "No - Isaac Newton (1643-1727) died 152 years before Albert Einstein"
         " was born (1879-1955)."),
        (["entity_1", "entity_2", "born_1", "died_1", "born_2", "died_2", "answer"],
         [("A", "B", 1900, None, 1950, None, None)],
         "Not enough in the extract to say - A (b. 1900) and B (b. 1950) overlapped."),
        (["entity_1", "entity_2", "age_1", "age_2", "answer"],
         [("Ludwig van Beethoven", "Wolfgang Amadeus Mozart", 57, 35, True)],
         "Yes - Ludwig van Beethoven lived 57 years, Wolfgang Amadeus Mozart 35."),
        (["entity_1", "entity_2", "works_1", "works_2", "answer"],
         [("Beethoven", "Mozart", 1234, 890, True)],
         "Yes - Beethoven has 1,234 works in the extract, Mozart 890."),
        (["entity_1", "entity_2", "country_1", "country_2", "answer"],
         [("Bach", "Beethoven", "Germany", "Germany", True)],
         "Yes - both from Germany."),
        (["entity_1", "entity_2", "country_1", "country_2", "answer"],
         [("Mozart", "Beethoven", "Austria", "Germany", False)],
         "No - Mozart from Austria; Beethoven from Germany."),
        (["entity_1", "entity_2", "entity_3", "age_1", "age_2", "age_3", "answer"],
         [("Bach", "Beethoven", "Mozart", 65, 57, 35, "Bach")],
         "Bach - 65 years, against Beethoven 57 and Mozart 35."),
        (["entity_1", "entity_2", "entity_3", "born_1", "born_2", "born_3", "answer"],
         [("Bach", "Beethoven", "Mozart", 1685, 1770, 1756, "Bach")],
         "Bach - born 1685, against Beethoven 1770 and Mozart 1756."),
        (["work", "year", "sitelinks"],
         [("Symphony No. 1", 1799, 40), ("Symphony No. 2", 1801, 38),
          ("Symphony No. 3", 1803, 55), ("Symphony No. 4", 1806, 33)],
         "4 works: Symphony No. 1 (1799), Symphony No. 2 (1801),"
         " Symphony No. 3 (1803) and 1 more."),
        (["person", "born", "died", "sitelinks"],
         [("Hermann Zoestius", 1420, 1480, 3)],
         "1 person: Hermann Zoestius (1420-1480)."),
        (["person", "location", "sitelinks"],
         [("Albert Einstein", "Ulm", 200)],
         "Albert Einstein - Ulm."),
        (["work", "year", "sitelinks"], [], "Nothing in the extract matches that."),
        #BC years reach here as negative numbers, from items like the Darius Painter
        (["person", "born", "died", "sitelinks"], [("Darius Painter", -400, -320, 9)],
         "1 person: Darius Painter (400 BC-320 BC)."),
    ]
    failures = 0
    for columns, rows, expected in cases:
        got = describe(columns, rows)
        if got == expected:
            print(f"ok   {got}")
        else:
            print(f"FAIL expected: {expected}\n     got:      {got}")
            failures += 1

    #the row-limit qualifier, which needs the limit the caller used
    got = describe(["work", "year", "sitelinks"],
                   [("W", 1800, 1)] * 200, limit=200)
    if got.startswith("200+ works:"):
        print(f"ok   {got[:40]}...")
    else:
        print(f"FAIL limit qualifier: {got[:60]}")
        failures += 1

    print("\nall checks passed" if not failures else f"\n{failures} check(s) failed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(_self_check())
