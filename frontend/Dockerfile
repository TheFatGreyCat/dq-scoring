# Static SPA image: bun builds, unprivileged nginx serves. API traffic is routed by the ingress, not this container.
# Build from the repo root so the root .dockerignore drops node_modules/dist:
#   docker build -f frontend/Dockerfile -t dq-scoring-ui:<tag> .
FROM oven/bun:1.4.2 AS build
WORKDIR /app
COPY frontend/package.json frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY frontend/ ./
RUN bun run build

FROM nginxinc/nginx-unprivileged:stable-alpine
COPY frontend/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
# UID 101 (nginx) is the image's non-root user; the chart runs it with a read-only root filesystem.
USER 101
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
