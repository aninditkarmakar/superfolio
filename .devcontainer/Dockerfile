FROM mcr.microsoft.com/devcontainers/typescript-node:4-24-trixie

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libdbd-pg-perl \
        postgresql-client \
        sqitch \
    && rm -rf /var/lib/apt/lists/*
