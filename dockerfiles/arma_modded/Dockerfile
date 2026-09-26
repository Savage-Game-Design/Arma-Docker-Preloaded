# STEAM_USERNAME and STEAM_PASSWORD should be defined as docker secrets
ARG ARMA_IMAGE="savagegamedesign/arma"
ARG ARMA_VERSION="latest"

FROM ${ARMA_IMAGE}:${ARMA_VERSION}

# Semicolon separated list of steam workshop ids: 12345;678910;12345
ARG MODLIST=""

WORKDIR /arma
USER arma
# Refresh scripts folder - allows us to update scripts without an Arma reinstall
COPY ../../scripts ./scripts/

RUN --mount=type=secret,id=STEAM_USERNAME,env=STEAM_USERNAME \
    --mount=type=secret,id=STEAM_PASSWORD,env=STEAM_PASSWORD \
    python3 ./scripts/install-mods.py "${MODLIST}"

# The build context root is mounted, rather than the folders themselves, so the build
# succeeds when extra_mods/ or missions/ do not exist. The scripts skip a missing folder.
RUN --mount=type=bind,target=/context \
    python3 ./scripts/install-mods-from-folder.py /context/extra_mods

RUN --mount=type=bind,target=/context \
    python3 ./scripts/install-missions-from-folder.py /context/missions
