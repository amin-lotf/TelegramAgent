# Official Telegram Bot API server (https://github.com/tdlib/telegram-bot-api).
# Builds only from the official TDLib source — no third-party packages or images.

FROM debian:12-slim AS build

ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    printf '%s\n' \
        'Acquire::Retries "5";' \
        'Acquire::ForceIPv4 "true";' \
        > /etc/apt/apt.conf.d/80-retries; \
    apt-get update -o Acquire::Retries=5 --fix-missing; \
    apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        gperf \
        git \
        libssl-dev \
        zlib1g-dev; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src

# Optional pin: docker build --build-arg TELEGRAM_BOT_API_GIT_REF=<tag-or-commit>
ARG TELEGRAM_BOT_API_GIT_REF=master

RUN git clone --recursive https://github.com/tdlib/telegram-bot-api.git . \
    && git checkout "${TELEGRAM_BOT_API_GIT_REF}" \
    && git submodule update --init --recursive

WORKDIR /src/build

RUN cmake \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX:PATH=/usr/local \
        .. \
    && cmake --build . --target install -j"$(nproc)"


FROM debian:12-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN set -eux; \
    printf '%s\n' \
        'Acquire::Retries "5";' \
        'Acquire::ForceIPv4 "true";' \
        > /etc/apt/apt.conf.d/80-retries; \
    apt-get update -o Acquire::Retries=5 --fix-missing; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libssl3 \
        zlib1g; \
    rm -rf /var/lib/apt/lists/*; \
    mkdir -p /var/lib/telegram-bot-api /tmp/telegram-bot-api

COPY --from=build /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-bot-api

VOLUME ["/var/lib/telegram-bot-api"]

EXPOSE 8081

# TELEGRAM_API_ID and TELEGRAM_API_HASH are read from the environment by the
# official binary (or may be passed as --api-id / --api-hash).
CMD [ \
    "telegram-bot-api", \
    "--local", \
    "--http-port=8081", \
    "--http-ip-address=0.0.0.0", \
    "--dir=/var/lib/telegram-bot-api", \
    "--temp-dir=/tmp/telegram-bot-api" \
]
