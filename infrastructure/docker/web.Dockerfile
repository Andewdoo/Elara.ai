FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json

# Install the web workspace from the lockfile before copying its source. This
# keeps the image reproducible and ensures `next` is available to its scripts.
RUN npm ci --workspace=@elara/web

COPY apps/web ./apps/web

# Never carry a host-generated Next/Turbopack cache into the Linux image.
RUN rm -rf ./apps/web/.next

WORKDIR /app/apps/web

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]
