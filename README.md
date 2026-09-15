# Pocket Ledger

Pocket Ledger is a private spending and savings app you can run on your own computer. Track transactions, regular bills, budgets, accounts, savings goals and commuting costs. It also includes mortgage and savings calculators. Your records stay in the Docker data volume on the computer where you run it.

## Start with Docker Compose

1. Install [Docker Desktop](https://docs.docker.com/desktop/) and open it. On Linux, you can use [Docker Engine with Compose](https://docs.docker.com/compose/install/).
2. On this GitHub page, select **Code → Download ZIP**. Unzip it and open a terminal in the folder containing `compose.prod.yaml`.
3. Copy and run:

   ```text
   docker compose -f compose.prod.yaml up -d
   ```

4. Open [http://127.0.0.1:5000](http://127.0.0.1:5000) on that computer. Create your account with a password of at least 12 characters.

The Compose file downloads the published `0.1.0` image and keeps your data in a Docker volume. To see whether it is running, use `docker compose -f compose.prod.yaml ps`. To stop it, use `docker compose -f compose.prod.yaml stop`; run the command in step 3 to start it again.

## Sample Compose file

If you prefer to make your own Compose file, create an empty folder and save the following as `compose.yaml` in that folder. You do not need to download the repository.

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
      - "127.0.0.1:5000:5000"
    volumes:
      - ledger-data:/data

volumes:
  ledger-data:
```

Open a terminal in that folder and run `docker compose up -d`. Then open [http://127.0.0.1:5000](http://127.0.0.1:5000). The `ledger-data` volume keeps your records when the container stops or is replaced. The `127.0.0.1` address limits access to the computer running Docker. To check or stop the app, run `docker compose ps` or `docker compose stop` in the same folder.

## Use Docker without Compose

If you already use Docker and just want to start the image, copy these commands into a terminal:

```text
docker volume create pocket-ledger-data
docker run -d --name pocket-ledger --restart unless-stopped -p 127.0.0.1:5000:5000 -v pocket-ledger-data:/data ghcr.io/mariof1/pocket-ledger:0.1.0
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). Later, use `docker stop pocket-ledger` and `docker start pocket-ledger` to stop or start it without deleting your data.

## Keep your data safe

Both options save accounts and records in a Docker volume, separate from the downloaded files. Back up that volume before moving to another computer or upgrading. **Profiles & settings → Export all data** can move records to a new user, but a full server backup must also keep the database and signing key. See the [backup and upgrade steps](DEPLOYMENT.md).

The supplied setup opens only on the computer running Docker. For access from other devices, follow the [HTTPS setup instructions](DEPLOYMENT.md).

For help using bills, statement imports, profiles and calculators, see the [user guide](USER_GUIDE.md). Developers can find [tests and contribution notes](CONTRIBUTING.md) and the [build pipeline](https://github.com/mariof1/pocket-ledger/actions/workflows/pipeline.yml). See [releases](https://github.com/mariof1/pocket-ledger/releases) for newer published images.
