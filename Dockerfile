FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AMACFA_STATE_DIR=/var/lib/amacfa
WORKDIR /app
COPY requirements.txt requirements-integrations.txt ./
RUN pip install --no-cache-dir -r requirements-integrations.txt \
    && groupadd --gid 10001 amacfa \
    && useradd --uid 10001 --gid 10001 --no-create-home amacfa \
    && install -d -m 0700 -o amacfa -g amacfa /var/lib/amacfa
COPY main.py ./
COPY amacfa ./amacfa
USER amacfa
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s CMD python -c "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/healthz', timeout=2).close()"
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "32"]
