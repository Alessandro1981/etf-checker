ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN apk add --no-cache bashio ca-certificates python3 py3-pip && \
    pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY app ./app
COPY run.sh /run.sh

RUN chmod a+x /run.sh

EXPOSE 8099

CMD ["/run.sh"]
