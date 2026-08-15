# Compact deployment (Productization v0.1.1): builds both portals from
# the same workspace and packages them into a single nginx image —
# User Portal at "/", Admin Portal at "/admin/". This is NOT a network
# boundary between them (see docs/security-model.md) — both are static
# files served by the same container, same as before this work. The
# Segmented example (docker-compose.segmented.yml) instead builds and
# serves each portal from its own dedicated container/origin.
#
# Build context is the repo root (docker-compose.yml), not frontend/, so
# this can also copy in docs/*.md for the in-app Help menus.
FROM node:26-slim AS build
WORKDIR /app
COPY frontend/package.json ./
COPY frontend/package-lock.json ./
COPY frontend/shared/package.json shared/package.json
COPY frontend/user/package.json user/package.json
COPY frontend/admin/package.json admin/package.json
RUN npm ci

COPY frontend/shared/ shared/
COPY frontend/user/ user/
COPY frontend/admin/ admin/

RUN npm run build --workspace=user
RUN npm run build --workspace=admin

FROM nginx:1.27-alpine
ARG OPENRBI_VERSION=1.0.1
ARG OPENRBI_COMMIT_SHA=unknown
ARG OPENRBI_BUILD_DATE=unknown
LABEL org.opencontainers.image.title="OpenRBI Frontend" \
      org.opencontainers.image.version="$OPENRBI_VERSION" \
      org.opencontainers.image.revision="$OPENRBI_COMMIT_SHA" \
      org.opencontainers.image.created="$OPENRBI_BUILD_DATE"
# Pulls in whatever OS security patches Alpine has released since this tag
# was last pulled (A5) — verified to actually close real findings here,
# unlike the Debian-based images where the equivalent apt-get upgrade left
# the remaining CVEs unfixed upstream (see .trivyignore).
RUN apk update && apk upgrade --no-cache
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/user/dist /usr/share/nginx/html
COPY --from=build /app/admin/dist /usr/share/nginx/html/admin
# Served at /docs/*.md from either portal's origin (absolute path), so a
# Help link works the same whether the Admin Portal is reached at /admin/
# (Compact) or its own origin root (Segmented, OPENRBI_ADMIN_BASE_PATH=/).
COPY docs/ /usr/share/nginx/html/docs/
COPY docs/ /usr/share/nginx/html/admin/docs/
RUN printf '{"version":"%s","commit_sha":"%s","build_date":"%s"}\n' \
    "$OPENRBI_VERSION" "$OPENRBI_COMMIT_SHA" "$OPENRBI_BUILD_DATE" \
    > /usr/share/nginx/html/version.json
EXPOSE 80
