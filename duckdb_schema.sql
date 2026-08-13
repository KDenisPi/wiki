-- Schema for wiki.duckdb, as built by load_duckdb.py.
--
-- load_duckdb.py normally creates these tables itself, one per CSV, via
-- CREATE OR REPLACE TABLE ... AS SELECT (so it infers types from that
-- pipeline and this file is not required to run it). This script documents
-- the resulting shape and can be used to stand up an empty database with the
-- same tables ahead of a load, or for tooling that expects them to exist.
--
-- No table carries a primary key or foreign key: the CSVs are the source of
-- truth, constraints would only slow the bulk load down, and every join in
-- queries.sql relies on qid/pid columns lining up rather than declared
-- references. The relationships are noted in comments below instead.


-- One row per Wikidata item.
CREATE TABLE items (
    qid             VARCHAR,  -- Wikidata QID, e.g. Q42
    label           VARCHAR,
    description     VARCHAR,
    label_ru        VARCHAR,
    description_ru  VARCHAR
);


-- One row per (item, date-property) fact.
CREATE TABLE events (
    qid            VARCHAR,   -- -> items.qid
    property       VARCHAR,   -- -> properties.pid, e.g. P569 (date of birth)
    "class"        VARCHAR,   -- -> classes.qid / item_classes."class"
    time_raw       VARCHAR,   -- original Wikidata time string, e.g. +1991-02-12T00:00:00Z
    year           BIGINT,    -- signed; not INTEGER, e.g. Big Bang is -13800000000
    month          UTINYINT,  -- 0 = precision unknown
    day            UTINYINT,  -- 0 = precision unknown
    bc             BOOLEAN,
    timezone       INTEGER,
    qual_property  VARCHAR,   -- nullable
    qual_value     VARCHAR    -- nullable
);


-- Non-date claims: one row per (item, property, value).
CREATE TABLE attributes (
    qid       VARCHAR,  -- -> items.qid
    property  VARCHAR,  -- -> properties.pid
    value     VARCHAR   -- -> value_items.qid
);


-- Item membership in the P279 class closure.
CREATE TABLE item_classes (
    qid     VARCHAR,  -- -> items.qid
    "class" VARCHAR   -- -> classes.qid
);


-- Labels/descriptions for QIDs that appear as attribute values.
CREATE TABLE value_items (
    qid          VARCHAR,
    label        VARCHAR,
    description  VARCHAR
);


-- The curated P31 whitelist, tagged with the domain(s) it belongs to.
CREATE TABLE classes (
    qid          VARCHAR,
    label        VARCHAR,
    description  VARCHAR,
    domains      VARCHAR  -- e.g. 'music,science'
);


-- Property dictionary.
CREATE TABLE properties (
    pid          VARCHAR,  -- e.g. P569
    label        VARCHAR,
    description  VARCHAR,  -- nullable
    kind         VARCHAR   -- 'date' | 'attribute' | 'other'
);
