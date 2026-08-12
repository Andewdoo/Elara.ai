FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json

# Install the web workspace from the lockfile before copying its source. This
# keeps the image reproducible and ensures `next` is available to its scripts.
RUN npm ci --workspace=@elara/web

COPY apps/web ./apps/web

# Never carry a host-generated Next/Turbopack cache into the Linux image.
RUN rm -rf ./apps/web/.next \
    && mkdir -p ./apps/web/.next \
    && addgroup -S elara \
    && adduser -S -D -H -u 10001 -G elara elara \
    && chown -R elara:elara ./apps/web

WORKDIR /app/apps/web

USER elara

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]
