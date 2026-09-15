FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY housat/ housat/
ENV PYTHONPATH=/srv

RUN useradd -r -u 1000 housat
USER housat

CMD ["python", "-m", "housat.worker", "--once"]
