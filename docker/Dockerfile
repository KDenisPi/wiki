# The wiki question service (agent/wiki_service.py) - the backend of
# AI_agents' MCP tools at :8000/wiki and of the kiosk's /api/wiki.
#
# Build from the repo root:
#   docker build -f docker/Dockerfile -t wiki-server:latest .
#
# The image holds Python and the two packages only. The code, the
# AI_agents repo it imports OllamaClient from, and the database are all
# bind-mounted at run time, the way AI_agents' own containers mount theirs -
# so a code change needs a container restart, not a rebuild. agent/*.py
# finds AI_agents at ../AI_agents relative to the repo root, so the two
# repos are mounted side by side; the database goes anywhere --db says.
#   docker run -d --name wiki-server -u 1000:1000 -p 8200:8200 \
#       -v /home/denis/projects/wiki:/projects/wiki \
#       -v /home/denis/projects/AI_agents:/projects/AI_agents:ro \
#       -v /home/denis/projects/wiki_data:/data:ro \
#       wiki-server:latest python -u agent/wiki_service.py --db /data/run7/wiki.duckdb
# AI_agents' start_all.sh runs exactly that, with log rotation.

FROM python:3.12-slim

WORKDIR /projects/wiki

COPY docker/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# AI_agents is mounted read-only, so Python could not write its bytecode
# cache there anyway; the wiki repo's own __pycache__ is not worth the
# writes either - the service imports once and runs for weeks.
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8200
