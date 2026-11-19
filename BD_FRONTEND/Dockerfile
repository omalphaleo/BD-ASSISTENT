# Three-stage build (deps, build, standalone run) for the Next.js frontend skeleton (task B1).
# Verified with a direct `docker build` and `docker run`; the image serves the placeholder page.
# Requires package-lock.json, a public/ folder and `output: "standalone"` in next.config.ts.
# No secrets here: only NEXT_PUBLIC_* values, which are public by definition, are build args.

FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-slim AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-slim AS run
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
