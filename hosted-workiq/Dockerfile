FROM mcr.microsoft.com/devcontainers/python:3.12
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY allowlist.py toolbox_mcp.py dry_run.py main.py /app/
EXPOSE 8088
CMD ["python3", "main.py"]
