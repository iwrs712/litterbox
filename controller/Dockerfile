# syntax=docker/dockerfile:1.7

FROM golang:1.25-bookworm AS build

ARG TARGETOS
ARG TARGETARCH

WORKDIR /src
COPY go.mod go.sum ./
RUN GOSUMDB=off go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS="${TARGETOS:-linux}" GOARCH="${TARGETARCH:-amd64}" \
    go build -trimpath -ldflags='-s -w' -o /out/controller ./cmd/controller

FROM scratch

COPY --from=build /out/controller /controller
USER 65532:65532
ENTRYPOINT ["/controller"]
