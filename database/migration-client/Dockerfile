# syntax=docker/dockerfile:1
# Alpine 3.24.2 linux/amd64 manifest digest; update deliberately with the CI scan.
FROM alpine:3.24@sha256:d56c381f961d307a21b3ca004cf1e3910f106644aefb1f43e654c8a56c4fd395

RUN apk add --no-cache \
      ca-certificates=20260909-r0 \
      postgresql17-client=17.11-r0 \
    && command -v psql \
    && command -v pg_isready \
    && psql --version \
    && pg_isready --version

# The migration Job uses this non-root UID/GID in Kubernetes as well.
USER 1654:1654
ENTRYPOINT ["psql"]
