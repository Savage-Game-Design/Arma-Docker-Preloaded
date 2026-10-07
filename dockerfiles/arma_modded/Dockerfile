# STEAM_USERNAME and STEAM_PASSWORD should be defined as docker secrets
ARG ARMA_IMAGE="savagegamedesign/arma"
ARG ARMA_VERSION="latest"

# Local content comes from a named build context called "local", which can point anywhere:
#   docker build --build-context local=/path/to/content ...
#   compose: build.additional_contexts: { local: ../content }
# When no such context is given, this empty stage is used in its place.
FROM scratch AS local

FROM ${ARMA_IMAGE}:${ARMA_VERSION}

# Print installer output as it happens rather than in buffered chunks.
ENV PYTHONUNBUFFERED=1

# Each content step installs whatever its sources contain: both mods or missions. 
# Separating ARMA_MISSIONS from ARMA_MODS allows missions to be updated without redownloading mods.

# A record of everything installed is kept in installed_content.json and is printed on startup.

# Semicolon separated list of Steam workshop ids and/or URLs to .zip or .pbo files:
#   "450814997;https://example.com/mods.zip"
ARG ARMA_MODS=""
# Deprecated: use ARMA_MODS. Still honoured, its entries are merged into ARMA_MODS.
ARG MODLIST=""

WORKDIR /arma
USER arma
# Refresh scripts folder - allows us to update scripts without an Arma reinstall
COPY ../../scripts ./scripts/

RUN --mount=type=secret,id=STEAM_USERNAME,env=STEAM_USERNAME \
    --mount=type=secret,id=STEAM_PASSWORD,env=STEAM_PASSWORD \
    python3 ./scripts/install_content.py --mods "${ARMA_MODS}" --legacy-modlist "${MODLIST}"

# Semicolon separated list of Steam workshop ids, "<id>=<name>.<map>" overrides, and/or URLs to
# .zip or .pbo files. 
ARG ARMA_MISSIONS=""

RUN --mount=type=secret,id=STEAM_USERNAME,env=STEAM_USERNAME \
    --mount=type=secret,id=STEAM_PASSWORD,env=STEAM_PASSWORD \
    python3 ./scripts/install_content.py --missions "${ARMA_MISSIONS}"

# Semicolon separated paths, relative to the "local" build context, to folders that are or contain mods/missions. 
# Only the "local" context is mounted, so this step only re-runs when that content changes.
ARG ARMA_LOCAL=""

RUN --mount=type=bind,from=local,target=/local \
    python3 ./scripts/install_content.py --local "${ARMA_LOCAL}" --local-root /local
