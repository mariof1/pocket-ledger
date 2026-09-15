# Deploy Pocket Ledger

Pocket Ledger stores credentials and financial records in SQLite. Keep its data volume private and persistent. The container listens on port 5000 internally; both Compose examples publish that port only on the host's `127.0.0.1`. Put an HTTPS reverse proxy in front of that loopback port before allowing access from another device, and set `LEDGER_HTTPS=1` so session cookies use the Secure flag.

## Run the released image

On a host with Docker Compose, the file uses the `0.1.0` release by default. Start it with:

```text
docker compose -f compose.prod.yaml pull
docker compose -f compose.prod.yaml up -d
docker compose -f compose.prod.yaml ps
```

Open `http://127.0.0.1:5000/api/bootstrap` on the Docker host to verify that the app responds.

To use another published version, set `LEDGER_IMAGE_TAG` in your shell or an `.env` file beside `compose.prod.yaml`, such as `LEDGER_IMAGE_TAG=0.2.0`. The `ledger-data` named volume stores `ledger.sqlite3` and `secret.key`. The signing key is created with owner-only file permissions; protect the volume because the database and key are stored unencrypted. `docker compose down` keeps the volume; do not use `down -v` on a deployment you want to retain. The image runs as UID/GID 10001, drops Linux capabilities, uses a read-only root filesystem and a small temporary filesystem, and exposes a health check. A custom bind mount for `/data` must be writable by UID 10001.

To build locally instead of pulling GHCR:

```sh
docker compose up --build -d
docker compose ps
```

The local build is labelled `dev`. The running app reports its image version in Profiles & settings and the `X-Pocket-Ledger-Version` response header. Stop any existing process using host port 5000 before starting either Compose example.

## Portainer stack

Paste this into a Portainer **Stack** and deploy it. It uses host port 5005 and joins an existing network named `prodNetwork`; change or remove the network section if your setup differs. Keep the same stack name and `data` volume when redeploying so existing records remain available.

```yaml
services:
  ledger:
    image: ghcr.io/mariof1/pocket-ledger:0.1.0
    init: true
    restart: unless-stopped
    read_only: true
    user: "10001:10001"
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:rw,noexec,nosuid,size=16m
    ports:
      - "5005:5000"
    volumes:
      - data:/data
    networks:
      - prodNetwork

volumes:
  data:

networks:
  prodNetwork:
    external: true
```

The image runs as UID/GID 10001 and protects `/app` so other users cannot read its code. Do not override it with `user: "1000:1000"`: the server will fail to import `app`. An existing custom `/data` mount must also be writable by UID 10001. If Portainer shows `permission denied` for `/data` after changing the user, check the mount's ownership; keep the volume and its database and signing key while fixing permissions.

Port 5005 is reachable through the host's network interfaces. Use an HTTPS reverse proxy before accessing financial records from another device. If the proxy connects over `prodNetwork`, you can remove the `ports` section; the proxy can reach the container on port 5000. Set `LEDGER_HTTPS=1` in the stack environment when requests reach the app over HTTPS, so session cookies are marked Secure.

## Upgrade and back up

Before changing image tags, make a verified online database backup inside the volume:

```sh
docker compose -f compose.prod.yaml exec ledger python backup_database.py
```

The command prints the path under `/data/backups/`. Also keep an off-host copy of the data volume, including `secret.key`; the database backup command does not copy the signing key. Then change `LEDGER_IMAGE_TAG` to the new released version, run `docker compose -f compose.prod.yaml pull`, and `docker compose -f compose.prod.yaml up -d`. Check `docker compose -f compose.prod.yaml ps` and `/api/bootstrap`. SQLite migrations run transactionally at startup and refuse to open a database newer than the app supports.

For rollback, stop the container, keep a copy of the current data volume, restore the chosen SQLite backup to `/data/ledger.sqlite3`, and start the image version that created that backup. Keep the same `secret.key` with the restored database. A release tag is an immutable image selection; `main` and `latest` tags move as new builds are published.

## Version and release flow

`dev` is the integration branch and `main` is the release source. Both currently contain the same work. Every push or pull request runs Python tests, migration/backup tests, browser JavaScript checks, mortgage tests, and a Docker build with a persistence smoke test. A successful `main` push publishes `ghcr.io/mariof1/pocket-ledger:main` and a `sha-...` tag. A `vX.Y.Z` tag whose number matches `VERSION` and whose commit belongs to `main` publishes `X.Y.Z` and `latest`, then creates a GitHub release. The published image includes BuildKit provenance and an SBOM for amd64 and arm64.

To prepare a new release, update `VERSION` in a reviewed commit on `dev`, merge it into `main`, wait for the `main` pipeline to pass, then create and push an annotated tag such as `v0.2.0` on that exact main commit. The tag pipeline must pass before the release and versioned image appear. Git commits in the repository to date have `mariof1` as both author and committer; the local repository is configured with `mariof1`'s GitHub noreply address.
