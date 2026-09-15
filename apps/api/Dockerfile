FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY pipeline/requirements.txt pipeline/requirements.txt
COPY apps/api/requirements.txt apps/api/requirements.txt
RUN pip install --no-cache-dir -r pipeline/requirements.txt -r apps/api/requirements.txt

COPY pipeline/ pipeline/
COPY apps/api/ api/

ENV PYTHONPATH=/srv/pipeline:/srv/api
EXPOSE 8000
RUN useradd -r -u 1000 housat
USER housat

CMD ["uvicorn", "main:app", "--app-dir", "api", "--host", "0.0.0.0", "--port", "8000"]
