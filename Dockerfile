FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# requirements.lock pins the full dependency tree; regenerate it with
# pip freeze from a clean venv when bumping requirements.txt
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

# uid 1000 matches the VPS user owning the bind-mounted ./data volume
RUN useradd --create-home --uid 1000 app

COPY bot ./bot

USER app

CMD ["python", "-m", "bot.main"]
