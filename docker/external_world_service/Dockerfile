ARG BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-bookworm
FROM ${BASE_IMAGE}
RUN pip install --no-cache-dir PyYAML==6.0.3
RUN useradd --create-home service
COPY app.py /srv/app.py
USER service
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/srv/app.py", "--host", "0.0.0.0", "--config", "/config/world_profile.yaml"]
