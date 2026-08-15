# Dependency locking and updates

OpenRBI installs application dependencies from committed lockfiles. Version
ranges in `pyproject.toml` and `package.json` describe intent; the lockfiles are
the reproducible installation inputs used by production images and CI.

## Python

The authoritative production and development locks are:

- `backend/requirements.lock` and `backend/requirements-dev.lock`
- `session-agent/requirements.lock` and `session-agent/requirements-dev.lock`

They target Python 3.11 on x86_64 Linux, the supported v1 production platform,
and include hashes for every artifact. Production images install the production
lock with `pip --require-hashes`; integration runners install the development
lock the same way.

To update them, install the pinned compiler and regenerate all four files:

```sh
python -m pip install uv==0.8.13
sh scripts/lock-python-dependencies.sh
```

Never edit a generated lock by hand. Review the resolved-version diff, run both
Python dependency audits, then run the release gates. CI regenerates the locks
and rejects a manifest change whose matching locks were not committed.

## Node.js

`frontend/package-lock.json` is authoritative for both portals. CI and the
frontend image use `npm ci`, which fails if it disagrees with any workspace
manifest. For an intentional update, run `npm install` in `frontend/`, review
the lockfile diff, then verify with `npm ci`, both workspace builds, and the npm
audit release gate.

Locking application packages does not pin container base-image or operating-
system package digests. Those artifacts remain covered by the image build and
Trivy gates and are addressed separately by the release-image work.
