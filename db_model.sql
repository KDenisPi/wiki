-- WiKi database model - DuckDB.
--
-- This is the structure load_duckdb.py builds out of the wpars output. The
-- loader creates the tables itself with CREATE OR REPLACE TABLE ... AS SELECT,
-- so this file is not needed to load data; it is the written-down model of the
-- result, and it stands up an empty database with the same tables for tooling
-- that expects them to exist.
--
-- Run it with the DuckDB CLI. The ATTACH names the database file, so the file
-- does not have to be on the command line - both of these end up in the same
-- place:
--
--   duckdb < db_model.sql              -- creates ./wiki.duckdb
--   duckdb wiki.duckdb < db_model.sql  -- same database, already open
--
-- Every table is CREATE TABLE IF NOT EXISTS, so running this against a loaded
-- database changes nothing and cannot drop rows.
--
-- The MySQL version of this model was replaced when the project moved to
-- DuckDB; it is in git history as `git show 7febd4b:db_model.sql`. Its column
-- widths no longer hold anyway - labels run past VARCHAR(30) and `year` needs
-- more than SMALLINT (see the note on events below).
--
-- No table carries a primary key, a foreign key or an index:
--   - the CSVs are the source of truth and every load rebuilds the tables, so
--     constraints would only slow the bulk load down;
--   - the workload is analytical (group by century, filter by occupation or
--     country, join events to items), which DuckDB answers by scanning columns
--     with zone maps rather than by seeking through an index.
-- The relationships are written in the comments instead. They hold: the
-- January extract had 0 orphans in events, attributes and item_classes.

ATTACH IF NOT EXISTS 'wiki.duckdb' AS wiki;
USE wiki;


-- -----------------------------------------------------
-- Dictionaries
-- -----------------------------------------------------

-- One row per selected Wikidata item: everything that has at least one date
-- and belongs to at least one class of interest. Source: ItemsExt.csv.
CREATE TABLE IF NOT EXISTS items (
    qid             VARCHAR,  -- Wikidata QID, e.g. Q42
    "label"         VARCHAR,  -- English label
    description     VARCHAR,
    label_ru        VARCHAR,  -- second language, see get_sites() in gconfig.h
    description_ru  VARCHAR
);

-- Property dictionary, tagged with the role the property plays here.
-- Source: properties.json plus the two selection files.
CREATE TABLE IF NOT EXISTS properties (
    pid          VARCHAR,  -- e.g. P569
    "label"      VARCHAR,  -- e.g. date of birth
    description  VARCHAR,
    kind         VARCHAR   -- 'date' | 'attribute' | 'other'
);

-- The P31 whitelist: every class reachable from a seed through P279, tagged
-- with the domain(s) that seed belongs to. Built by build_class_closure.py.
-- Source: select_classes.csv.
CREATE TABLE IF NOT EXISTS classes (
    qid          VARCHAR,
    "label"      VARCHAR,
    description  VARCHAR,
    domains      VARCHAR   -- '|' separated, e.g. 'event|literature|music'.
                           -- A closed set of seven tags, one per seed group:
                           -- art, event, literature, music, person, place,
                           -- science. Any other value matches nothing.
);

-- Labels for the QIDs that turn up as attribute values (occupations,
-- countries, places, genres). Resolved out of the full item dump by
-- resolve_values.py, because those items are not selected in their own right.
-- Source: values.csv.
CREATE TABLE IF NOT EXISTS value_items (
    qid          VARCHAR,
    "label"      VARCHAR,
    description  VARCHAR
);


-- Which area each occupation belongs to. A question says "scientists" and P106
-- records a profession: the 15th century has 58,088 dated people, of whom 50
-- are labelled "scientist" and the rest are astronomers, physicians and
-- mathematicians. Built by build_occupation_areas.py from the P279 closure of a
-- few area roots, kept to the occupations the extract actually uses.
-- Source: occupation_areas.csv.
CREATE TABLE IF NOT EXISTS occupation_areas (
    qid          VARCHAR,  -- the QID a P106 attribute row points at
    "label"      VARCHAR,  -- e.g. astronomer
    areas        VARCHAR,  -- '|' separated: art, literature, music, science
    people       BIGINT    -- how many people in the extract hold it
);


-- -----------------------------------------------------
-- Facts
-- -----------------------------------------------------

-- One row per (item, date property, class) fact - the events the questions are
-- asked about. Source: DataEvents.csv, loaded with DISTINCT.
--
-- The Wikidata time string is kept as it arrived and also split into columns,
-- since the questions are about years and centuries.
CREATE TABLE IF NOT EXISTS events (
    qid            VARCHAR,   -- -> items.qid
    property       VARCHAR,   -- -> properties.pid, e.g. P569 (date of birth)
    "class"        VARCHAR,   -- -> classes.qid
    time_raw       VARCHAR,   -- as in the dump, e.g. +1991-02-12T00:00:00Z
    "year"         BIGINT,    -- signed. Not SMALLINT: 40 rows in the January
                              -- extract were already outside 16 bits. Not even
                              -- INTEGER: the Big Bang is -13800000000.
    "month"        UTINYINT,  -- 0 when the source has no month precision
    "day"          UTINYINT,  -- 0 when the source has no day precision
    bc             BOOLEAN,   -- true for a negative year, e.g. Caesar -0044
    timezone       INTEGER,
    qual_property  VARCHAR,   -- claim qualifier, nullable
    qual_value     VARCHAR    -- nullable
);

-- Non-date claims: occupation, citizenship, place of birth, genre and the rest
-- of attribute_properties.csv. One row per (item, property, value) - an item
-- with three occupations has three rows. Source: Attributes.csv, DISTINCT.
CREATE TABLE IF NOT EXISTS attributes (
    qid       VARCHAR,  -- -> items.qid
    property  VARCHAR,  -- -> properties.pid
    "value"   VARCHAR   -- -> value_items.qid
);

-- Which classes an item belongs to. Separate from events because an item is
-- normally an instance of several classes, and a question can arrive through
-- any of them. Source: ItemClasses.csv, DISTINCT.
CREATE TABLE IF NOT EXISTS item_classes (
    qid      VARCHAR,  -- -> items.qid
    "class"  VARCHAR   -- -> classes.qid
);

-- Wikipedia presence per item. sitelinks is the notability signal used to rank
-- answers - it is the only one the dump offers - and the titles are the join
-- key to article text, should the Wikipedia dataset be pulled in later.
-- Source: ItemSites.csv.
CREATE TABLE IF NOT EXISTS sites (
    qid        VARCHAR,  -- -> items.qid
    sitelinks  INTEGER,  -- number of Wikipedia editions holding the item
    enwiki     VARCHAR,  -- English article title, NULL when there is none
    ruwiki     VARCHAR   -- Russian article title, NULL when there is none
);


-- What the database holds now. Zero rows everywhere means the tables were just
-- created and the loader has not run yet.
SELECT table_name, estimated_size AS rows, column_count AS columns
FROM duckdb_tables()
WHERE database_name = 'wiki'
ORDER BY table_name;
