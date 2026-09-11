# Builds the static frontend. The final image holds only /app/dist; an nginx (or
# other) image elsewhere mounts or copies it. Build context: the frontend/ dir.
#
#   docker build -t grader-frontend ./frontend
#   docker create --name f grader-frontend && docker cp f:/app/dist ./dist && docker rm f

FROM node:22-alpine AS build
WORKDIR /app
RUN corepack enable && corepack prepare pnpm@11.1.2 --activate
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm check && pnpm build

FROM scratch AS dist
COPY --from=build /app/dist /app/dist
