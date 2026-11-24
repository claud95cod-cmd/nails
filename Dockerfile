FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py schema.sql ./
COPY templates templates
COPY static static
RUN install -d -o 65534 -g 65534 /var/lib/booking-media
USER 65534:65534
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8000","--no-access-log"]
