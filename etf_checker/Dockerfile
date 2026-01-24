ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

WORKDIR /app

COPY requirements.txt ./requirements.txt
ENV VIRTUAL_ENV=/opt/venv

RUN apk add --no-cache bash ca-certificates python3 py3-pip && \
    python3 -m venv "${VIRTUAL_ENV}" && \
    "${VIRTUAL_ENV}/bin/pip" install --no-cache-dir --upgrade pip setuptools wheel && \
    "${VIRTUAL_ENV}/bin/pip" install --no-cache-dir -r requirements.txt

ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"

COPY app ./app
COPY run.sh /run.sh

RUN chmod a+x /run.sh

EXPOSE 8099

ENTRYPOINT ["/init"]
CMD ["/run.sh"]
