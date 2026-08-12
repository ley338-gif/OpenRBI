# Compact deployment (Productization v0.1.1): builds both portals from
# the same workspace and packages them into a single nginx image —
# User Portal at "/", Admin Portal at "/admin/". This is NOT a network
# boundary between them (see docs/security-model.md) — both are static
# files served by the same container, same as before this work. The
# Segmented example (docker-compose.segmented.yml) instead builds and
# serves each portal from its own dedicated container/origin.
FROM node:22-slim AS build
WORKDIR /app
COPY package.json ./
COPY shared/package.json shared/package.json
COPY user/package.json user/package.json
COPY admin/package.json admin/package.json
RUN npm install

COPY shared/ shared/
COPY user/ user/
COPY admin/ admin/

RUN npm run build --workspace=user
RUN npm run build --workspace=admin

FROM nginx:1.27-alpine
# Pulls in whatever OS security patches Alpine has released since this tag
# was last pulled (A5) — verified to actually close real findings here,
# unlike the Debian-based images where the equivalent apt-get upgrade left
# the remaining CVEs unfixed upstream (see .trivyignore).
RUN apk update && apk upgrade --no-cache
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/user/dist /usr/share/nginx/html
COPY --from=build /app/admin/dist /usr/share/nginx/html/admin
EXPOSE 80
