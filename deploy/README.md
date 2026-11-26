# Deployment (AWS)

One EC2 server in Stockholm (`eu-north-1`) runs the whole system with Docker:
PostgreSQL + pgvector, the FastAPI backend, the Next.js frontend, and Caddy
in front, which obtains the HTTPS certificate itself.

| | |
|---|---|
| Address | https://13-50-76-30.sslip.io |
| Server | EC2 `t3.small` (2 vCPU, 2 GB + 2 GB swap), Ubuntu 24.04, 20 GB encrypted disk, tag `Name=elimu` |
| Fixed IP | Elastic IP 13.50.76.30 (sslip.io turns it into a hostname - no domain needed) |
| Firewall | Security group `elimu-web`: 80 and 443 open, 22 only from the deploy machine's IP |
| Cost | About US$21/month while running (instance ~$16, IPv4 ~$3.65, disk ~$1.60) |

Images are built on the deploy machine, not on the server: 2 GB is enough to
run the app but not to build the Next.js app and install PyTorch.

## Secrets

`/opt/elimu/.env` on the server, mode 600, never committed. `JWT_SECRET` and
`POSTGRES_PASSWORD` were generated on the server and have never left it.

```
SITE_HOST=13-50-76-30.sslip.io
POSTGRES_PASSWORD=...
JWT_SECRET=...
ANTHROPIC_API_KEY=...      reports and AI question writing
GOOGLE_CLIENT_ID=...       optional - Sign in with Google
GOOGLE_CLIENT_SECRET=...
```

After changing it: `docker compose up -d` in `/opt/elimu`.

For Google sign-in, add `https://13-50-76-30.sslip.io/api/auth/google/callback`
as an authorised redirect URI on the Google Cloud OAuth client.

## Redeploy after a code change

From the repository root, on a machine with Docker and the SSH key:

```bash
HOST=ubuntu@13.50.76.30
docker build -t elimu-frontend:latest frontend
docker build -t elimu-backend:latest -f backend/Dockerfile .
docker save elimu-backend:latest elimu-frontend:latest | gzip | ssh -i ~/.ssh/elimu-aws $HOST 'gunzip | docker load'
scp -i ~/.ssh/elimu-aws deploy/docker-compose.yml deploy/Caddyfile $HOST:/opt/elimu/
ssh -i ~/.ssh/elimu-aws $HOST 'cd /opt/elimu && docker compose up -d && docker image prune -f'
```

If the schema changed (`models.py`), reseed - this **deletes all data**:

```bash
ssh -i ~/.ssh/elimu-aws $HOST 'cd /opt/elimu && docker compose run --rm backend python -m app.seed --reset \
  && docker compose run --rm backend python -m app.ingest_curriculum \
  && docker compose run --rm backend python -m app.ingest_rubrics'
```

## Everyday operations

```bash
ssh -i ~/.ssh/elimu-aws ubuntu@13.50.76.30
cd /opt/elimu
docker compose ps                 # all four should be "Up"
docker compose logs -f backend    # server errors appear here, not in the browser
docker compose restart backend
```

**SSH refused?** The firewall only admits the IP that set it up, and a
Codespace's address changes. In the AWS console: EC2 -> Security Groups ->
`elimu-web` -> Edit inbound rules -> the SSH rule -> Source "My IP".

**Stop paying between demonstrations:** EC2 -> Instances -> `elimu` ->
Instance state -> Stop. The data, address and certificate survive; only the
disk and IP are billed (~$5/month). Start it again the same way; the app
starts on boot.

**Remove everything:** terminate the instance, release the Elastic IP, delete
the security group and the `elimu-deploy` key pair, then delete the
`elimu-deploy` IAM user.
