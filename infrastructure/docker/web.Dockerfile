FROM node:22-alpine

WORKDIR /app

COPY apps/web /app

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]

