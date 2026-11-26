# AWX execution environment for this repository: the AWX 24.6.1 EE (the version
# the app cluster runs) plus the pinned Doppler CLI, which four roles call on the
# controller (`delegate_to: localhost`). See docs/awx.md.
FROM quay.io/ansible/awx-ee:24.6.1@sha256:89593d2a0268acacdbd1c075d8810ab50d961cf7769e36de19219bb6cb4efcc1

LABEL org.opencontainers.image.source="https://github.com/fabricesemti80/home-dc-proxmox" \
      org.opencontainers.image.description="AWX EE with the Doppler CLI for home-dc-proxmox"

ARG DOPPLER_VERSION=3.77.1
ARG DOPPLER_SHA256=001f89a42629f9cb827cd86683c4c2dbf87c6299a8d6130643b98044bf5ed80a

USER root
RUN curl -fsSL -o /tmp/doppler.tar.gz \
      "https://github.com/DopplerHQ/cli/releases/download/${DOPPLER_VERSION}/doppler_${DOPPLER_VERSION}_linux_amd64.tar.gz" \
 && echo "${DOPPLER_SHA256}  /tmp/doppler.tar.gz" | sha256sum -c - \
 && tar -xzf /tmp/doppler.tar.gz -C /usr/local/bin doppler \
 && rm -f /tmp/doppler.tar.gz \
 && doppler --version
USER 1000
