# UNTESTED: written before the Next.js app exists (BD_FRONTEND/ has no package.json yet).
# Revisit and test when the Next.js skeleton is added (plan.md M1 frontend task).
# Assumes a standard Next.js App Router project with `output: "standalone"` in next.config.ts.
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
