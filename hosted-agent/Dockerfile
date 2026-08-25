FROM mcr.microsoft.com/devcontainers/javascript-node:22 AS nodebuild
WORKDIR /src
COPY package.json /src/package.json
RUN npm install --omit=dev --ignore-scripts
COPY agent.mjs /src/agent.mjs
RUN bash -lc 'set -euo pipefail; \
  NODE_BIN=$(readlink -f "$(command -v node)"); \
  mkdir -p /export/app; \
  cp "$NODE_BIN" /export/node; \
  cp -a /src/node_modules /export/app/node_modules; \
  cp /src/package.json /src/agent.mjs /export/app/; \
  ls -lh /export/node'

FROM mcr.microsoft.com/devcontainers/python:3.12
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY --from=nodebuild /export/node /usr/local/bin/node
COPY --from=nodebuild /export/app/node_modules /app/node_modules
COPY --from=nodebuild /export/app/package.json /app/package.json
COPY --from=nodebuild /export/app/agent.mjs /app/agent.mjs
COPY main.py /app/main.py
ENV NODE_PATH=/app/node_modules
USER root
ENTRYPOINT []
EXPOSE 8088
CMD ["python3", "main.py"]
