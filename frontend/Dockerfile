# ---- deps: shared base for both the dev and prod-build stages ----
FROM node:20-slim AS deps

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

# ---- dev: Vite dev server, used only via docker-compose.dev.yml ----
FROM deps AS dev

COPY . .
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host"]

# ---- builder: type-checks (tsc -b) and produces the static bundle ----
FROM deps AS builder

COPY . .
RUN npm run build

# ---- runtime (default target): Caddy serves the SPA, proxies /api ----
FROM caddy:2-alpine AS runtime

COPY --from=builder /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile

EXPOSE 80 443
