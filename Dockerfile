FROM python:3.11-slim
WORKDIR /srv
COPY serve_https.py .
COPY server.key server.crt .
EXPOSE 8443
CMD ["python3", "serve_https.py", "--port", "8443", "--dir", "/srv"]
