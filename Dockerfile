FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# uid 1000 matches the VPS user owning the bind-mounted ./data volume
RUN useradd --create-home --uid 1000 app

COPY bot ./bot

USER app

CMD ["python", "-m", "bot.main"]
