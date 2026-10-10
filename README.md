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
- A Steam account for the vanilla image and for any workshop id in `ARMA_MODS` or
  `ARMA_MISSIONS`. The account needs to own Arma 3 to download Creator DLCs or workshop content,
  and can't answer Steam Guard prompts during a build. Installing mods that only use URLs and
  local folders doesn't require credentials, as long as the base Arma docker image exists.
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
  --build-arg "ARMA_MODS=450814997;3083451905;https://example.com/my_mods.zip" \
  --build-arg "ARMA_MISSIONS=1234567890;2345678901=coop_town.altis;https://example.com/coop.altis.pbo" .
```

`ARMA_MODS` and `ARMA_MISSIONS` each take a semicolon-separated mix of Steam workshop ids and
`https://` URLs to `.zip` or `.pbo` files. Ensure the value is quoted as the the shell treats 
`;` as a command separator.

Both `ARMA_MODS` and `ARMA_MISSIONS` can contain either missions or mods. It's recommended
anything large go in `ARMA_MODS`, so that they aren't redownloaded when `ARMA_MISSIONS` changes.

`ARMA_LOCAL` lists paths to install from the `local` build context folder, for example missions
or mods you already have copies of on the build machine. `ARMA_LOCAL` is run last, and changes 
to it do not trigged a new download of `ARMA_MODS` or `ARMA_MISSIONS`.

| Source | What it installs | How to load it |
|---|---|---|
| Workshop id | A mod as `@<id>`, plus an `@<name>` symlink named after the `name` in its `meta.cpp`, lower-cased with spaces replaced by underscores (`CBA_A3 Beta` becomes `@cba_a3_beta`). An item that is a single loose `.pbo` is a mission instead, see below | `-mod=@<id>` or `-mod=@<name>` |
| URL to a `.zip` | Every mod and mission inside, read by the rules below | `-mod=@<folder>`, `ARMA_CFG_MISSION_1_TEMPLATE=<name>.<map>` |
| URL to a `.pbo` | One mission, named after the file in the URL | `ARMA_CFG_MISSION_1_TEMPLATE=<name>.<map>` |
| Path in `ARMA_LOCAL` | A mod folder, a `.pbo` mission, or a folder holding either, read by the rules below | as for a zip |

Mods land in `/arma/server/@<folder>` and missions in `/arma/server/mpmissions/`, all lower-cased.
`ARMA_LOCAL` paths are relative to a content folder passed as a named build context called
`local`, which can be anywhere on the machine and need not be inside this repository:

```bash
docker build -f dockerfiles/arma_modded/Dockerfile -t my-org/arma-modded:latest \
  --build-context local=/srv/arma-content \
  --build-arg "ARMA_LOCAL=@my_mod;missions/coop.altis.pbo;packs" .
```

In Compose, set `build.additional_contexts: { local: /srv/arma-content }` (Compose 2.17 or
later). An empty folder is used if the build context isn't provided, so all `ARMA_LOCAL` entries will fail. 

A zip, or a folder listed in `ARMA_LOCAL`, is read as follows. The build log prints each item's `-mod=` name or mission template.
- A lone folder that is not itself a mod, such as `my-pack/` holding `@cba/` and `@ace/`, will
  be searched for mods. The mods must all be in the same folder.
- A zip that is itself a single mod (`addons/`, `mod.cpp` or `meta.cpp` at its root) is named
  after the zip file in the URL: `https://example.com/my_mod.zip` becomes `@my_mod`.
- Otherwise every top-level folder with `addons/`, `mod.cpp` or `meta.cpp` is one mod, named after
  the folder: a GitHub download holding `repo-main/addons/` becomes `@repo-main`.
- An `@` folder holding mod folders, such as `@Mods/@cba/` and `@Mods/@ace/`, is a wrapper: each
  child is a mod.
- Mods are never nested: a mod folder inside a mod is just part of the outer mod.
- `.pbo` files inside a mod stay in the mod. Any other `.pbo`, at the top or in a non-mod folder at
  any depth, is treated as a mission.
- Anything else is ignored, and builds fail if nothing is found in an `ARMA_LOCAL` entry.

Mod folder names are lower-cased and stripped to `a-z0-9_@.-`. Installing the same mod or mission
name twice will cause the build to fail. The exception is missions and mods from `ARMA_LOCAL`: these 
are copied over any existing mod/mission of the same name, replacing existing files if needed.

Mod keys are loaded at startup from every mod named in `-mod=` and `-servermod=`. 
Each mod's `keys` folder is passed to Arma with `-keysFolder`, so only the mods a server actually 
loads have their signatures accepted. The `keys` folder from the server directory is always included. 
If you pass your own `-keysFolder=`, the mod folders are appended to it, and `!keys` in your list still excludes the base folder.

A workshop item is a mission when its download is a single file with no mod folders, whichever
argument listed it. Steam records the upload under a mangled name ending in `.<map>.pbo`; DepotDownloader
keeps that name and steamcmd saves it as `<id>_legacy.bin`, so the map is taken from the local name or,
failing that, from Steam's record. The build then names the mission from the item's workshop title: lower-cased, accents removed, spaces to `_`, everything else
outside `a-z0-9_` removed. "My Great Mission! (v2)" on Stratis becomes
`my_great_mission_v2.stratis.pbo`, and "Opération Café" becomes `operation_cafe`. To pick the
name yourself, write the entry as `<id>=<name>.<map>` in `ARMA_MISSIONS`; no Steam lookup happens in that case. The
build fails if the title lookup fails, or if the map cannot be determined and no override is given.

Everything installed is recorded in `/arma/server/installed_content.json` (kind, name, title, origin,
keys and load hint), and the server prints it as a table at startup. The table's NAME column shows a mod's
`meta.cpp` name where it has one, and its folder name otherwise.

| Build arg | Purpose |
|---|---|
| `ARMA_IMAGE` | Base image name. Default `savagegamedesign/arma`. |
| `ARMA_VERSION` | Base image tag. Default `latest`. |
| `ARMA_MODS` | Semicolon-separated workshop ids and `.zip`/`.pbo` URLs, installed in the mods layer. Optional. |
| `ARMA_MISSIONS` | Semicolon-separated workshop ids, `<id>=<name>.<map>` overrides, and `.zip`/`.pbo` URLs, installed in the missions layer. Optional. |
| `ARMA_LOCAL` | Semicolon-separated paths in the `local` build context to mod folders, `.pbo` missions, or folders of either, installed last. Optional. |
| `MODLIST` | Deprecated alias for `ARMA_MODS`, still honoured. |

Each URL may download at most `ARMA_MAX_DOWNLOAD_BYTES` (default 20 GiB). A download that falls
below `ARMA_MINIMUM_DOWNLOAD_SPEED` MB/s (default 10) averaged over that cap, or that waits more than
`ARMA_DOWNLOAD_TIMEOUT_SECONDS` (default 60) for the connection or for any single read, fails. Each zip
may extract to at most `ARMA_MAX_EXTRACT_BYTES` (default 25 GiB). To change a limit, add an `ENV` line
to the modded Dockerfile before the install steps.

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
| `dockerfiles/arma_modded/` | Adds mods and missions from the workshop, URLs and local paths to a vanilla image. |
| `scripts/` | Build-time installers. The vanilla image copies only the Arma install files, so editing the content installers never re-downloads Arma. |
| `entrypoint/run.py` | Container entrypoint: generates config, then launches the server. Safe to modify without invalidating the cached Arma layer. |
| `server_config_generator/` | Config generator and defaults files. Safe to modify without invalidating the cached Arma layer. |
