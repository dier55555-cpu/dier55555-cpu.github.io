FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV COURT_KB_CORPUS=/app/data/corpus.jsonl \
    COURT_KB_COURTS_CONFIG=/app/courts.yaml

EXPOSE 8080

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
