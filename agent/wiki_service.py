#!/usr/bin/env python3
"""The wiki question pipeline as an HTTP service.

sentence_to_sql.py answers a question once, from the command line, and puts
the answer in its log. The AI agent side needs the same answers over the
network - MCP clients through AI_agents' McpMultiHttpServer.py, which proxies
the tools at /wiki to this service, and the kiosk through ai_agent_server.py.
It is a separate process on purpose: it needs duckdb and the 2.1 GB database,
neither of which belongs in the lightweight mcp-server container, and it
keeps the dependency one-way - this repo already imports OllamaClient from
AI_agents, so AI_agents talks to this one over HTTP rather than importing it.

One endpoint per step of the pipeline, so a caller can stop wherever it has
what it needs:

    GET  /health     {"status": "ok", "db": <path>}
    GET  /tools      the four MCP tool definitions below - names,
                     descriptions and input schemas. The proxy serves these
                     as they are, so the intent schema has one owner: this
                     file, next to the composer that reads it.
    POST /sentence   {"question"} -> step 0 only: question, question_used,
                     step0_note
    POST /intent     {"question"} -> step 0, stage 1, the leader-word fill and
                     name resolution: the above plus intent, notes, unplaced.
                     No SQL is run.
    POST /query      an intent (or {"intent": ...}) -> name resolution and
                     stage 2: intent, notes, unplaced, sql, status, answer,
                     columns, rows, row_count. For a caller whose own model
                     has already read the question into an intent.
    POST /ask        {"question"} -> all of it.

Every answer is JSON. A pipeline that ran but found nothing, or whose SQL
failed, is still 200 - "status" and "answer" say what happened; 4xx is a
request this service cannot read, 503 a queue that stayed full, 500 a step
that raised.

At most --max-rows rows go back (row_count is the total), and at most
--concurrency questions run at once: each one is a model call or two and a
DuckDB query that can keep a core busy for seconds, and the rest wait their
turn for up to --queue-timeout seconds.

In service it runs in Docker as wiki-server (docker/Dockerfile; SETUP.md has
the run command, and AI_agents' start_all.sh starts it). By hand (the
pipeline's own options pass through - see sentence_to_sql.py):

    /home/denis/projects/venv-duckdb2/bin/python agent/wiki_service.py
    /home/denis/projects/venv-duckdb2/bin/python agent/wiki_service.py --port 8200 --db <path>

    curl -s localhost:8200/ask -d '{"question": "Show me France kings when Michel de Montaigne was alive?"}'

Unlike the command line, nothing is written to a training log unless
--training-log names one.
"""

import argparse
import json
import logging
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import sentence_to_sql as pipeline
from intent_to_sql import DOMAINS, TARGET_TYPES, TIME_RELATIONS

logger = logging.getLogger("wiki_service")

#A request body is a question or an intent; anything this large is neither.
MAX_BODY_BYTES = 64 * 1024

_QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {
            "type": "string",
            "description": "The question in plain English, as the user asked it.",
        },
    },
    "required": ["question"],
}

#What intent_to_sql.build_sql reads - the same fields, values and meanings
#the stage 1 prompt (sentence_to_sql_stage1_context.txt) teaches the model,
#written for a caller's model to fill in instead.
INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "target_type": {
            "type": "string",
            "enum": list(TARGET_TYPES),
            "description": "What the answer is about: people, works (books, symphonies, "
                           "paintings, inventions...) or events (wars, battles, elections...).",
        },
        "answer_field": {
            "type": ["string", "null"],
            "enum": ["time", "location", "places", None],
            "description": "null to return the matching entities themselves (the usual case). "
                           "'time' when the question asks WHEN about a named target, 'location' "
                           "for WHERE it was born/built/held, 'places' for every place a "
                           "person's life touched ('where did X live').",
        },
        "filters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": ["string", "null"],
                    "description": "The target's own name when the question is about one named "
                                   "person, work or event ('Albert Einstein', 'Symphony No. 5'). "
                                   "null when the target is described by occupation, place or time.",
                },
                "occupation": {
                    "type": ["string", "null"],
                    "description": "Person targets only. A profession, singular and lowercase "
                                   "('composer', 'physicist', 'painter'); 'leaders' or 'rulers' "
                                   "for a country's leaders of any kind; or a ruler's title - "
                                   "king, queen (consorts count), emperor, empress, tsar, tsarina, "
                                   "sultan, shah, pharaoh, caliph, khan, doge, grand duke, grand "
                                   "prince, president, prime minister, chancellor - which is "
                                   "matched against the offices people actually held.",
                },
                "subject": {
                    "type": ["string", "null"],
                    "description": "Work and event targets only: the kind of thing, singular, in "
                                   "the question's words ('symphony', 'novel', 'battle').",
                },
                "location": {
                    "type": ["string", "null"],
                    "description": "A place name in English ('France', 'Russia', 'Germany'), also "
                                   "for a nationality adjective ('French composers' -> 'France'). "
                                   "For people: citizenship, birth, death, work or residence; for "
                                   "a ruler's title, a country named in the office counts too. "
                                   "For events where they happened, for works where they come from.",
                },
                "domain": {
                    "type": ["string", "null"],
                    "enum": list(DOMAINS) + [None],
                    "description": "The broad field, from this closed list only, or null: "
                                   "composers -> music, writers -> literature, physicists and "
                                   "inventions -> science, painters -> art, wars and battles -> event.",
                },
                "time_constraint": {
                    "type": ["object", "null"],
                    "description": "A period, in one of two shapes. "
                                   "{type: 'in_range', start_year, end_year, precision: 'year'|"
                                   "'decade'|'century', event: 'born'|'died'|'alive'} - event is "
                                   "for people; 'alive' (the default) means alive at some point in "
                                   "the range; the Nth century is (N-1)*100+1 to N*100. Or "
                                   "{type: 'relative_to_entity', relation: 'overlap'|'before'|"
                                   "'after', entity_mention: <a person named in the question>} "
                                   "for 'when X was alive', 'before X', 'after X'.",
                    "properties": {
                        "type": {"type": "string", "enum": ["in_range", "relative_to_entity"]},
                        "start_year": {"type": "integer"},
                        "end_year": {"type": "integer"},
                        "precision": {"type": "string", "enum": ["year", "decade", "century"]},
                        "event": {"type": "string", "enum": ["born", "died", "alive"]},
                        "relation": {"type": "string", "enum": list(TIME_RELATIONS)},
                        "entity_mention": {"type": "string"},
                    },
                },
                "related_entity": {
                    "type": ["object", "null"],
                    "description": "Another named entity the targets are linked to: "
                                   "{relation: 'creates'|'participates_in'|'located_in', "
                                   "entity_mention}. 'creates' names the work for person targets "
                                   "('who wrote Hamlet' -> 'Hamlet') and the creator for work "
                                   "targets ('works by Newton' -> 'Newton').",
                    "properties": {
                        "relation": {"type": "string",
                                     "enum": ["creates", "participates_in", "located_in"]},
                        "entity_mention": {"type": "string"},
                    },
                },
                "compare_entities": {
                    "type": ["object", "null"],
                    "description": "Two or more NAMED entities compared with each other: "
                                   "{entities: [names as in the question], aspect: 'time'|"
                                   "'work_count'|'age'|'location', relation: overlap/before/after "
                                   "for time, more/fewer/equal for work_count and age, "
                                   "same/different for location, work_type: the kind of work "
                                   "counted, or null}. Not for a group like 'kings of France' - "
                                   "that is occupation and location.",
                    "properties": {
                        "entities": {"type": "array", "items": {"type": "string"}},
                        "aspect": {"type": "string",
                                   "enum": ["time", "work_count", "age", "location"]},
                        "relation": {"type": "string"},
                        "work_type": {"type": ["string", "null"]},
                    },
                },
            },
        },
    },
    "required": ["target_type", "filters"],
}

_ABOUT = ("A Wikidata extract (dump of 2025-09-22) of people, works and events: dates of "
          "birth and death, places, occupations, offices held with their years, who created "
          "what and who took part in what.")

_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False,
              "idempotentHint": True, "openWorldHint": False}

TOOLS = [
    {
        "name": "wiki_sentence",
        "description": "Show how the wiki pipeline's first step reads a question: its spelling "
                       "and grammar corrected, as the later steps would see it. Returns question "
                       "(as typed), question_used and step0_note (what was changed, or why a "
                       "change was refused). Nothing is looked up.",
        "inputSchema": _QUESTION_SCHEMA,
        "annotations": _READ_ONLY,
    },
    {
        "name": "wiki_intent",
        "description": "Show how the wiki pipeline understands a question, without answering "
                       "it: the corrected question and the structured intent it was read into "
                       "(the same shape wiki_query takes), with notes on anything filled in or "
                       "re-spelled. Use it to check or adjust an intent before wiki_query.",
        "inputSchema": _QUESTION_SCHEMA,
        "annotations": _READ_ONLY,
    },
    {
        "name": "wiki_query",
        "description": "Answer a question already read into a structured intent. " + _ABOUT +
                       " Fill in the intent from the user's question yourself - every field not "
                       "asked about is null. Returns the answer as one sentence, the rows behind "
                       "it, the SQL that ran, and notes on names re-spelled to the database's.",
        "inputSchema": INTENT_SCHEMA,
        "annotations": _READ_ONLY,
    },
    {
        "name": "wiki_ask",
        "description": "Answer a question in plain English about people, works and events "
                       "of history. " + _ABOUT + " Runs the whole pipeline: corrects the "
                       "question, reads it into an intent, queries the database. Returns the "
                       "question actually used, the intent, the answer as one sentence and the "
                       "rows behind it.",
        "inputSchema": _QUESTION_SCHEMA,
        "annotations": _READ_ONLY,
    },
]


class BadRequest(Exception):
    """A request this service cannot read - answered 400 with the reason."""


def _intent_value(text):
    """The intent as JSON when it is JSON, otherwise the text stage 1 returned."""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


class WikiService:
    """The endpoints' work, apart from HTTP so it can be called directly."""

    def __init__(self, args: argparse.Namespace, max_rows: int):
        self.args = args
        self.max_rows = max_rows

    def _answer(self, result: dict) -> dict:
        """Stage 2's outcome with the rows as objects, and no more of them
        than a caller's context should have to hold."""
        columns, rows = result.get("columns") or [], result.get("rows") or []
        shown = [dict(zip(columns, row)) for row in rows[: self.max_rows]]
        return {"status": result.get("status"), "error": result.get("error"),
                "answer": result.get("answer"), "sql": result.get("sql"),
                "sql_source": result.get("sql_source"), "columns": columns or None,
                "rows": shown, "row_count": result.get("row_count"),
                "rows_truncated": len(rows) > len(shown)}

    @staticmethod
    def _question(body: dict) -> str:
        question = body.get("question")
        if not isinstance(question, str) or not question.strip():
            raise BadRequest('expected {"question": "<text>"}')
        return question.strip()

    def sentence(self, body: dict) -> dict:
        return pipeline.step0(self.args, self._question(body))

    def intent(self, body: dict) -> dict:
        fixed = pipeline.step0(self.args, self._question(body))
        read = pipeline.stage1(self.args, fixed["question_used"])
        placed = pipeline.resolve(self.args, read["intent"])
        return {**fixed, "intent": _intent_value(placed["intent"]),
                "notes": read["notes"] + placed["notes"], "unplaced": placed["unplaced"]}

    def query(self, body: dict) -> dict:
        intent = body.get("intent", body)
        if not isinstance(intent, dict):
            raise BadRequest("expected an intent object, or {\"intent\": {...}}")
        if intent.get("target_type") not in TARGET_TYPES:
            raise BadRequest(f"target_type must be one of {', '.join(TARGET_TYPES)}")
        if not isinstance(intent.get("filters"), dict):
            raise BadRequest("filters must be an object")
        placed = pipeline.resolve(self.args, json.dumps(intent, ensure_ascii=False))
        answered = pipeline.stage2(self.args, placed["intent"], unplaced=placed["unplaced"])
        return {"intent": _intent_value(placed["intent"]), "notes": placed["notes"],
                "unplaced": placed["unplaced"], **self._answer(answered)}

    def ask(self, body: dict) -> dict:
        run = argparse.Namespace(**{**vars(self.args), "sentence": self._question(body)})
        result = pipeline.full_run(run)
        return {"question": result["question"], "question_used": result["question_used"],
                "step0_note": result["step0_note"], "intent": _intent_value(result["intent"]),
                "notes": result["notes"], "unplaced": result["unplaced"],
                **self._answer(result)}


def make_handler(service: WikiService, slots: threading.BoundedSemaphore,
                 queue_timeout: float):
    routes = {"/sentence": service.sentence, "/intent": service.intent,
              "/query": service.query, "/ask": service.ask}

    class Handler(BaseHTTPRequestHandler):
        server_version = "wiki-service/1"

        def log_message(self, fmt, *values):
            logger.info("%s %s", self.address_string(), fmt % values)

        def _send(self, code: int, payload) -> None:
            #rows can hold dates and decimals; str() is how a reader wants them
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/health":
                db = Path(service.args.db)
                self._send(200 if db.is_file() else 503,
                           {"status": "ok" if db.is_file() else "no database", "db": str(db)})
            elif self.path == "/tools":
                self._send(200, {"tools": TOOLS})
            else:
                self._send(404, {"error": f"no such endpoint: GET {self.path}"})

        def do_POST(self):
            route = routes.get(self.path)
            if route is None:
                self._send(404, {"error": f"no such endpoint: POST {self.path}"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY_BYTES:
                    raise BadRequest(f"body over {MAX_BODY_BYTES} bytes")
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise BadRequest("the body must be a JSON object")
            except (ValueError, BadRequest) as e:
                self._send(400, {"error": str(e)})
                return

            if not slots.acquire(timeout=queue_timeout):
                self._send(503, {"error": f"busy - no free slot within {queue_timeout:.0f}s"})
                return
            started = time.perf_counter()
            try:
                result = route(body)
            except BadRequest as e:
                self._send(400, {"error": str(e)})
                return
            except Exception as e:              # noqa: BLE001 - reported, not fatal
                logger.error("%s failed:\n%s", self.path, traceback.format_exc())
                self._send(500, {"error": f"{type(e).__name__}: {e}"})
                return
            finally:
                slots.release()
            result["seconds"] = round(time.perf_counter() - started, 2)
            logger.info("%s done in %.2fs (%s)", self.path, result["seconds"],
                        result.get("status") or "-")
            self._send(200, result)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(
        description="The wiki question pipeline over HTTP - see the module docstring. "
                    "Any option not listed here goes to the pipeline (sentence_to_sql.py "
                    "--help), e.g. --db, --url, --model1.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8200)
    parser.add_argument("--max-rows", type=int, default=50,
                        help="rows returned per answer at most; row_count is the total")
    parser.add_argument("--concurrency", type=int, default=2,
                        help="questions answered at the same time")
    parser.add_argument("--queue-timeout", type=float, default=120.0,
                        help="seconds a request waits for a free slot before a 503")
    parser.add_argument("--log-file", default=None, help="also log to this file")
    own, rest = parser.parse_known_args()

    args = pipeline.build_parser().parse_args(rest)
    if "--training-log" not in rest:
        args.training_log = None

    handlers = [logging.StreamHandler()]
    if own.log_file:
        Path(own.log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(own.log_file))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    service = WikiService(args, own.max_rows)
    slots = threading.BoundedSemaphore(own.concurrency)
    server = ThreadingHTTPServer((own.host, own.port),
                                 make_handler(service, slots, own.queue_timeout))
    server.daemon_threads = True
    logger.info("wiki service on %s:%d - db %s, stage 1 %s at %s, %d at a time",
                own.host, own.port, args.db, args.model1, args.url, own.concurrency)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    sys.exit(main())
