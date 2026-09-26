# Arma Docker Preloaded

Dockerfiles for Arma 3 dedicated servers with the game, Creator DLCs, mods and missions
built into the image. 

Server configuration and custom difficulty are set entirely through environment variables.

This:
- Enables many servers to share the same Arma install, minimising disk footprint
- Avoids having to mount server configs and profiles
- Facilitates atomic upgrades with minimal downtime (build the new base image, then re-deploy the containers)

This is designed to make hosting Arma with Docker Compose or container managers (e.g. Komodo, Dockhand, Portainer) simple.

## Requirements

- Docker with BuildKit (build secrets are used for Steam credentials).
- A Steam account. It must own Arma 3 to download Creator DLCs or workshop mods, and it
  cannot answer Steam Guard prompts during a build.
- Credentials in two files, each containing only the value:

  ```
  secrets/steam_username
  secrets/steam_password
  ```

  Keep `secrets/` out of version control.

All builds run from the repository root.

## Build the vanilla image

```bash
docker build -f dockerfiles/arma/Dockerfile -t savagegamedesign/arma:latest \
  --secret id=STEAM_USERNAME,src=./secrets/steam_username \
  --secret id=STEAM_PASSWORD,src=./secrets/steam_password \
  --build-arg CDLCS=vn .
```

| Build arg | Purpose |
|---|---|
| `CDLCS` | Comma-separated Creator DLC ids: `vn`, `gm`, `csla`, `ws`, `spe`, `rf`, `ef`. Optional. |
| `BRANCH` | Steam branch to install. Defaults to `creatordlc` when `CDLCS` is set. |

This downloads the whole server and is slow. `build_arma_image.sh` is a ready-made example
for Arma with S.O.G. Prairie Fire.

## Add mods and missions

The modded image builds on top of the vanilla one, avoiding unnecessary rebuilds when mods are changed.

```bash
docker build -f dockerfiles/arma_modded/Dockerfile -t my-org/arma-modded:latest \
  --secret id=STEAM_USERNAME,src=./secrets/steam_username \
  --secret id=STEAM_PASSWORD,src=./secrets/steam_password \
  --build-arg "MODLIST=450814997;3083451905" .
```

| Source | How to supply it | Where it's mounted | How to load it |
|---|---|---|---|
| Workshop mods | `--build-arg "MODLIST=<id>;<id>"` | `/arma/server/@<id>` | `-mod=@<id>` |
| Local mods | One folder per mod in `extra_mods/` | `/arma/server/@<folder>`, lower-cased | `-mod=@<folder>` or `-servermod=@<folder>` |
| Missions | `.pbo` files in `missions/` | `/arma/server/mpmissions/`, lower-cased | In-game or via `ARMA_CFG_MISSION_1_TEMPLATE` |

Workshop mod keys are copied into the server's `keys/` folder automatically - so only include mods you intend to use. 
Rebuild the image to use a different modset, rather than just unmounting them.

The `extra_mods/` and `missions/` folders are optional - create them only when you have missions to mount.

| Build arg | Purpose |
|---|---|
| `ARMA_IMAGE` | Base image name. Default `savagegamedesign/arma`. |
| `ARMA_VERSION` | Base image tag. Default `latest`. |
| `MODLIST` | Semicolon-separated workshop ids. Quote it on the command line, since the shell treats `;` as a command separator. Optional. |

## Run a server

Everything after the image is passed to the Arma server executable (via `run.py`).


```bash
docker run -d --name arma-server \
  -p 2302-2306:2302-2306/udp \
  -v arma-profiles:"/home/arma/.local/share/Arma 3 - Other Profiles" \
  -e ARMA_CFG_HOSTNAME="My Server" \
  -e ARMA_CFG_MAX_PLAYERS=24 \
  -e ARMA_CFG_MISSION_1_TEMPLATE=my_mission.altis \
  -e ARMA_CFG_MISSION_1_DIFFICULTY=Regular \
  savagegamedesign/arma:latest \
  -port=2302 -name=server1 -mod=vn
```

The same thing in Compose:

```yaml
services:
  arma:
    image: savagegamedesign/arma:latest
    ports:
      - "2302-2306:2302-2306/udp"
    volumes:
      - arma-profiles:/home/arma/.local/share/Arma 3 - Other Profiles
    environment:
      ARMA_CFG_HOSTNAME: "My Server"
      ARMA_CFG_MAX_PLAYERS: 24
      ARMA_CFG_MISSION_1_TEMPLATE: my_mission.altis
      ARMA_CFG_MISSION_1_DIFFICULTY: Regular
    command:
      - "-port=2302"
      - "-name=server1"
      - "-mod=vn"
    restart: always

volumes:
  arma-profiles:
```

- `-config=server.cfg` is added automatically, and `server.cfg` is regenerated on every start from environment variables. 
  Pass your own `-config=` to load a different file, in which case `ARMA_CFG_*` variables have no effect.
- Mounting a persistent volume for profiles is optional, but recommended. Many missions store their saves in the profile.
- Give each server its own `-name=`. It selects the profile, which holds mission persistence.
- For a different port, change both `-port=` and the published range, which is the port plus the next four.

## Configuration

Settings come from environment variables, falling back to
[`server_config_generator/defaults.env`](server_config_generator/defaults.env) inside the
image. `defaults.env` lists every supported variable with its type. Omitted variables use the engine's defaults.

| Prefix | Written to |
|---|---|
| `ARMA_CFG_*` | `server.cfg`. Covers every option on the [Bohemia wiki page](https://community.bistudio.com/wiki/Arma_3:_Server_Config_File). |
| `ARMA_DIFFICULTY_*` | Custom difficulty in `<name>.Arma3Profile`. Requires `-name=` to select the profile, and the mission load with the `Custom` difficulty. |

| Type | Format | Example |
|---|---|---|
| string, number | As written | `ARMA_CFG_VOTE_THRESHOLD=0.7` |
| flag | `0` or `1` | `ARMA_CFG_BATTLEYE=1` |
| bool | `true` or `false` | `ARMA_CFG_AUTO_SELECT_MISSION=true` |
| list | Items separated by `\|` | `ARMA_CFG_ADMINS=7656...\|7656...` |
| list of rows | Rows separated by `\|`, fields by `,` | `ARMA_CFG_KICK_TIMEOUT=0,-1\|1,20` |
| mission | `ARMA_CFG_MISSION_<N>_TEMPLATE`, `_DIFFICULTY`, `_NAME`, `_PARAMS` | `ARMA_CFG_MISSION_1_PARAMS=respawn=15\|tickets=5` |

- Any list also accepts a JSON array, such as `["a","b"]`.
- An empty value emits an empty string or array. The value `null` removes a default.
- Append `_FILE` to any variable to read its value from a file, for example
  `ARMA_CFG_PASSWORD_ADMIN_FILE=/run/secrets/admin_password`.
- `ARMA_CFG_EXTRA` is appended to `server.cfg` verbatim.
- An unknown or malformed variable stops the container at startup with an error, and the generated files can be found in the container logs.

Preview the output without Docker:

```bash
ARMA_CFG_HOSTNAME="Test" python3 server_config_generator/generate_server_config.py --print
```

## Layout

| Path | Contents |
|---|---|
| `dockerfiles/arma/` | Vanilla image: Arma 3 server plus Creator DLCs. |
| `dockerfiles/arma_modded/` | Adds workshop mods, local mods and missions to a vanilla image. |
| `scripts/` | Build-time installers. Changing them invalidates the Arma download layer. |
| `entrypoint/run.py` | Container entrypoint: generates config, then launches the server. Safe to modify without invalidating the cached Arma layer. |
| `server_config_generator/` | Config generator and defaults files. Safe to modify without invalidating the cached Arma layer. |
