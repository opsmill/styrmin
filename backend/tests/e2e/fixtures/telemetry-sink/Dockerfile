FROM python:3.14-slim

WORKDIR /sink
COPY sink.py ./

EXPOSE 8080

CMD ["python3", "-u", "sink.py"]
