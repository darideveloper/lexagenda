# The worker (`manage.py work`) runs faster-whisper `small` on CPU in this same image: the
# documented box for it is 2 vCPU / 4 GB (PLAN §16). Transcription is on-demand, one note at a
# time; the web container never loads the weights.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2"]
