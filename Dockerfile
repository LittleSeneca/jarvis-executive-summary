FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY jarvis/ jarvis/
COPY plugins/ plugins/

CMD ["python", "-m", "jarvis"]
