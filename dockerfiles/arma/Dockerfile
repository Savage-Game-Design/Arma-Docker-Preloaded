# Dockerfile elements reused from https://github.com/BrettMayson/Arma3Server

# STEAM_USERNAME and STEAM_PASSWORD should be defined as docker secrets

FROM debian:12-slim AS steamcmd

SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update \
    && \
    apt-get install -y --no-install-recommends --no-install-suggests \
        python3 \
        lib32stdc++6 \
        lib32gcc-s1 \
        libcurl4 \
        wget \
        ca-certificates \
        # Needed by Arma
        net-tools \
        # Needed to unpack depot downloader \
        unzip \
    && \
    apt-get remove --purge -y \
    && \
    apt-get clean autoclean \
    && \
    apt-get autoremove -y \
    && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /steamcmd \
    && \
    wget -qO- 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd_linux.tar.gz' | tar zxf - -C /steamcmd \
    && \
    # Download and update steamcmd
    bash /steamcmd/steamcmd.sh +quit

RUN mkdir -p /depotdownloader \
    && cd /depotdownloader \
    && wget -q -O 'DepotDownloader.zip' 'https://github.com/SteamRE/DepotDownloader/releases/download/DepotDownloader_3.4.0/DepotDownloader-linux-x64.zip' \
    && unzip ./DepotDownloader.zip \
    && rm ./DepotDownloader.zip

FROM steamcmd AS arma

ARG BRANCH=""
ARG CDLCS=""

RUN useradd -ms /bin/bash arma -u 1964

RUN mkdir /arma && chown -R arma:arma /arma

WORKDIR /arma

# Copy scripts one at a time, to minimise cache-breaks that mean we need to redownload Arma
COPY ../../scripts ./scripts/

USER arma

ENV ARMA_INSTALL_PATH=/arma/server
ENV STEAMCMD_PATH=/steamcmd/steamcmd.sh
ENV STEAMDEPOTDOWNLOADER_PATH=/depotdownloader/DepotDownloader
ENV CACHE_BREAK_DATE=2025-07-27
RUN --mount=type=secret,id=STEAM_USERNAME,env=STEAM_USERNAME \
    --mount=type=secret,id=STEAM_PASSWORD,env=STEAM_PASSWORD \
    python3 ./scripts/install.py --branch ${BRANCH} --cdlcs ${CDLCS}

# Create paths for Arma profiles
RUN mkdir -p /home/arma/.local/share/Arma\ 3 && mkdir -p /home/arma/.local/share/Arma\ 3\ -\ Other\ Profiles

EXPOSE 2302/udp
EXPOSE 2303/udp
EXPOSE 2304/udp
EXPOSE 2305/udp
EXPOSE 2306/udp

STOPSIGNAL SIGINT

COPY ../../entrypoint/run.py ./run.py
# Generates server.cfg from ARMA_CFG_* environment variables at container start
COPY ../../server_config_generator ./server_config_generator/

ENTRYPOINT ["python3","./run.py", "--"]
