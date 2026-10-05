FROM mcr.microsoft.com/playwright/python:v1.63.0-noble

WORKDIR /srv/browser
COPY services/browser/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY services/browser/app.py ./app.py
RUN chown -R pwuser:pwuser /srv/browser
USER pwuser
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8090
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1", "--no-access-log"]
