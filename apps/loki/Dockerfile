FROM ubuntu:24.04

# Install mount utilities and dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    sshfs \
    cifs-utils \
    ca-certificates \
    fuse3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Download LOKI-RS binary (Linux x86_64) from GitHub releases
ARG LOKI_VERSION=v2.10.0
RUN curl -L -o /tmp/loki.tar.gz \
    "https://github.com/Neo23x0/Loki-RS/releases/download/${LOKI_VERSION}/loki-linux-x86_64-${LOKI_VERSION}.tar.gz" && \
    mkdir -p /opt/loki && \
    tar xzf /tmp/loki.tar.gz -C /opt/loki && \
    rm /tmp/loki.tar.gz && \
    chmod +x /opt/loki/loki /opt/loki/loki-util && \
    apt-get purge -y curl && apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /opt/loki

# Pre-download signatures at build time
RUN ./loki-util update

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
