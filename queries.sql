-- Example queries against the DuckDB database built by load_duckdb.py.
--
-- Run the whole file, or open the database and paste one query at a time:
--
--   duckdb wiki.duckdb < queries.sql
--   duckdb wiki.duckdb
--
-- The Python library in /home/denis/projects/venv3.11 opens the same file
-- (both are v1.5.5, the storage format is tied to the version):
--
--   >>> import duckdb
--   >>> duckdb.connect('wiki.duckdb').sql("<paste a query>").show()
--
-- Tables: items, events, attributes, item_classes, sites, value_items,
-- classes, occupation_areas, properties - the model is in db_model.sql.
-- Queries 1 and 2 run on any build; the rest need attributes and item_classes,
-- which only exist after a run made with --attrs.


-- 1. What happened in a given year in music and science.
--    Items are matched through every class they belong to, and classes carry
--    the domain tag assigned by build_class_closure.py.
SELECT i.label,
       i.description,
       c.label   AS class,
       c.domains AS area,
       p.label   AS date_type,
       e.year
FROM events e
JOIN items i        USING (qid)
JOIN item_classes l USING (qid)
JOIN classes c      ON c.qid = l."class"
JOIN properties p   ON p.pid = e.property
WHERE e.year = 1875
  AND (c.domains LIKE '%music%' OR c.domains LIKE '%science%')
ORDER BY c.domains, i.label;


-- 2. The same question asked over a whole century, counted by area.
SELECT (e.year / 100)::BIGINT * 100 AS century,
       c.domains AS area,
       count(DISTINCT e.qid) AS items
FROM events e
JOIN item_classes l USING (qid)
JOIN classes c      ON c.qid = l."class"
WHERE e.year BETWEEN 1800 AND 1899
GROUP BY 1, 2
ORDER BY items DESC;


-- 3. Which scientists lived in Germany in the 1400s.
--    "Lived in" is read as born or died inside the window, which also keeps
--    people whose other date is unknown.
WITH lifespan AS (
    SELECT qid,
           max(year) FILTER (WHERE property = 'P569') AS born,
           max(year) FILTER (WHERE property = 'P570') AS died
    FROM events
    GROUP BY qid
),
occupation AS (
    SELECT a.qid, v.label AS occupation
    FROM attributes a
    JOIN value_items v ON v.qid = a.value
    WHERE a.property = 'P106'
),
citizenship AS (
    SELECT a.qid, v.label AS country
    FROM attributes a
    JOIN value_items v ON v.qid = a.value
    WHERE a.property = 'P27'
)
-- a person usually has several occupations and sometimes several
-- citizenships, so collapse them instead of repeating the person per row
SELECT i.label,
       string_agg(DISTINCT o.occupation, ', ') AS occupations,
       string_agg(DISTINCT z.country, ', ')    AS countries,
       min(l.born) AS born,
       min(l.died) AS died
FROM lifespan l
JOIN items i      USING (qid)
JOIN occupation o USING (qid)
JOIN citizenship z USING (qid)
WHERE z.country ILIKE '%German%'
  -- "scientist" is an area, not a job title - only 50 people dated to this
  -- century carry it, against 2,039 professions that occupation_areas puts
  -- under science
  AND EXISTS (SELECT 1 FROM attributes a
              JOIN occupation_areas oa ON oa.qid = a."value"
              WHERE a.qid = l.qid AND a.property = 'P106'
                AND list_contains(str_split(oa.areas, '|'), 'science'))
  AND (l.born BETWEEN 1400 AND 1499 OR l.died BETWEEN 1400 AND 1499)
GROUP BY i.label
ORDER BY born;


-- 4. Anyone by occupation and period, the generic form of query 3.
--    Change the two parameters at the top and the rest follows.
WITH params AS (SELECT 'composer' AS want_occupation, 1700 AS from_year, 1799 AS to_year),
lifespan AS (
    SELECT qid,
           max(year) FILTER (WHERE property = 'P569') AS born,
           max(year) FILTER (WHERE property = 'P570') AS died
    FROM events
    GROUP BY qid
)
SELECT i.label, v.label AS occupation, l.born, l.died
FROM attributes a
JOIN value_items v ON v.qid = a.value
JOIN items i       ON i.qid = a.qid
JOIN lifespan l    ON l.qid = a.qid
CROSS JOIN params
WHERE a.property = 'P106'
  AND v.label = params.want_occupation
  AND l.born BETWEEN params.from_year AND params.to_year
ORDER BY l.born;


-- 5. Musical works of a year with the people and genre attached to them.
SELECT i.label AS work,
       max(CASE WHEN a.property = 'P86'  THEN v.label END) AS composer,
       max(CASE WHEN a.property = 'P175' THEN v.label END) AS performer,
       max(CASE WHEN a.property = 'P136' THEN v.label END) AS genre,
       min(e.year) AS year
FROM events e
JOIN items i        USING (qid)
JOIN item_classes l USING (qid)
JOIN classes c      ON c.qid = l."class"
LEFT JOIN attributes a  ON a.qid = e.qid AND a.property IN ('P86', 'P175', 'P136')
LEFT JOIN value_items v ON v.qid = a.value
WHERE e.year = 1875
  AND c.domains LIKE '%music%'
GROUP BY i.label
ORDER BY i.label;


-- 6. Events of a period with where they happened and who took part.
SELECT i.label AS event,
       min(e.year) AS year,
       max(CASE WHEN a.property = 'P17'  THEN v.label END) AS country,
       max(CASE WHEN a.property = 'P276' THEN v.label END) AS location,
       string_agg(DISTINCT CASE WHEN a.property = 'P710' THEN v.label END, ', ') AS participants
FROM events e
JOIN items i        USING (qid)
JOIN item_classes l USING (qid)
JOIN classes c      ON c.qid = l."class"
LEFT JOIN attributes a  ON a.qid = e.qid AND a.property IN ('P17', 'P276', 'P710')
LEFT JOIN value_items v ON v.qid = a.value
WHERE e.year BETWEEN 1600 AND 1699
  AND c.domains LIKE '%event%'
GROUP BY i.label
ORDER BY year
LIMIT 50;


-- 7. Which occupations actually occur in the data.
--    This is the list to map onto areas (science, music, art) - far smaller
--    than the full occupation vocabulary, because only these are used.
SELECT v.label AS occupation, count(*) AS people
FROM attributes a
JOIN value_items v ON v.qid = a.value
WHERE a.property = 'P106'
GROUP BY 1
ORDER BY people DESC
LIMIT 200;


-- 8. Data quality.
--    Date precision: month = 0 means the source only knew the year.
SELECT p.label AS date_type,
       count(*) AS dates,
       count(*) FILTER (WHERE e.month = 0) AS year_only,
       count(*) FILTER (WHERE e.bc)        AS bc,
       min(e.year) AS earliest,
       max(e.year) AS latest
FROM events e
JOIN properties p ON p.pid = e.property
GROUP BY 1
ORDER BY dates DESC;

--    Attribute values that resolve_values.py could not label. Anything here
--    means the values file is stale against the extract.
SELECT a.property, count(*) AS unresolved
FROM attributes a
LEFT JOIN value_items v ON v.qid = a.value
WHERE v.qid IS NULL
GROUP BY 1
ORDER BY unresolved DESC;


-- 9. Works of a named creator.
--    Queries 5 and 6 attach attributes to show them, so they LEFT JOIN and
--    keep rows that have none. Here the attribute IS the filter, so it is an
--    inner JOIN and the name stands alone in the WHERE clause: a work with no
--    creator recorded must not come back. Softening this with
--    "OR a.property IS NULL" would let every work in the database through.
--    The three creator properties are tested together - which one a work uses
--    is not predictable: a book is P50, a symphony P86, a painting P170.
SELECT i.label AS work,
       min(e.year) AS year
FROM items i
JOIN attributes a  ON a.qid = i.qid AND a.property IN ('P50', 'P86', 'P170')
JOIN value_items v ON v.qid = a.value
LEFT JOIN events e ON e.qid = i.qid
WHERE v.label = 'Isaac Newton'
GROUP BY i.qid, i.label
ORDER BY year;
