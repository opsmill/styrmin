FROM alpine:3.20 AS builder

RUN apk add --no-cache curl

ARG TARGETARCH
RUN curl -fsSL https://get.helm.sh/helm-v3.16.4-linux-${TARGETARCH}.tar.gz | \
    tar xz -C /usr/local/bin --strip-components=1 linux-${TARGETARCH}/helm

WORKDIR /build
COPY driver/examples/simple-app/src/helm/ ./simple-app-chart/
RUN helm package --dependency-update ./simple-app-chart -d /repo

COPY driver/examples/db-test/src/helm/ ./db-test-chart/
RUN helm package --dependency-update ./db-test-chart -d /repo

RUN helm repo index /repo

FROM alpine:3.20

RUN apk add --no-cache python3
COPY --from=builder /repo /charts
WORKDIR /charts

EXPOSE 8080

CMD ["python3", "-m", "http.server", "8080"]
