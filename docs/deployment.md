# Deployment

Target: the maintainer's **Docker Swarm** (single machine). Image → **GHCR** (free for
public images; Actions push with the built-in token). Data is **not** baked into the
image — it's mounted as a volume.

## Files

- `Dockerfile` — slim serving image (~647 MB): base deps + embedding model, **no data**.
  Analysis libs (umap/hdbscan/sklearn) are excluded (they're in the optional `analysis`
  extra, used only for the offline `feed cluster`).
- `.dockerignore` — keeps `data/`, `.venv/`, `.git/` out of the build context (context ~700 KB).
- `docker/entrypoint.sh` — on start: optionally pull data (`$DATA_PULL_CMD`); **refuse to
  start without `data/vectors.sqlite`**; rebuild `index.sqlite` from `corpus.jsonl` if
  missing; then `uvicorn webapp.app:app`.
- `docker-stack.yml` — Swarm stack: 1 replica, named `data` volume at `/app/data`, port 8077.
- `.github/workflows/docker-publish.yml` — builds + pushes to `ghcr.io/<repo>` on `v*` tags.

Verified locally: image builds and serves the real 208k corpus (semantic search works)
when `./data` is mounted.

## Build & push

```bash
# local build/test
docker build -t iatromante:test .
docker run --rm -p 8078:8077 -v "$PWD/data:/app/data" iatromante:test

# publish: just push a tag — the GitHub Action builds + pushes to GHCR
git tag v0.1.0 && git push --tags
# (or manually: docker build/tag/push to ghcr.io/<owner>/iatromante)
```

## Deploy to Swarm

1. Edit `docker-stack.yml`: set `image: ghcr.io/<OWNER>/iatromante:latest`.
2. **Populate the data volume** with `vectors.sqlite` (+ `corpus.jsonl`). On a single-node
   swarm the volume is at `/var/lib/docker/volumes/iatromante_data/_data/`. Copy the files
   there, or bind-mount a host dir instead of the named volume. (`index.sqlite` will be
   rebuilt automatically.)
3. `docker stack deploy -c docker-stack.yml iatromante`

## Remaining deploy steps (not done yet)

- [ ] Set `<OWNER>` and push the first image tag.
- [ ] Get data onto the server (manual copy now; later `feed pull-data` from private HF —
      not built yet, see [roadmap.md](roadmap.md)).
- [ ] **Reverse proxy + TLS + auth gate** (nginx/Caddy). This is health-adjacent reading
      for a specific person — it should **not be public**. Add HTTP basic-auth or your
      usual SSO in front.
- [ ] Decide update cadence (see scheduling in [roadmap.md](roadmap.md)).

## Keeping it current (once deployed)

The "constant feed" loop (not yet automated):
```bash
feed fetch     # new papers (incremental once watermarks are set)
feed embed     # embed only the new ones (resumable)
feed index     # rebuild keyword index
feed cluster   # periodically (weekly) — re-cluster as the corpus grows
```
Note: watermarks in `state.json` are **not set yet**, so the first scheduled `feed fetch`
will re-scan from `backfill_start` (2015) once (dedup-safe, just slow that once).
