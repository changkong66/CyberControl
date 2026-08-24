ARG PYTHON_IMAGE=python:3.11-alpine@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4
ARG BACKEND_IMAGE=cybercontrol/gate-c-backend:unknown

FROM ${PYTHON_IMAGE} AS jemalloc-compiled

ARG JEMALLOC_SOURCE_SHA256=2db82d1e7119df3e71b7640219b6dfe84789bc0537983c3b7ac4f7189aecfeaa
ARG MUSL_PATCH_SHA256=555b08620f00919e9b99c98a433cfcb755359395d62622cc8ae967d6717d43a0
ARG PKGCONF_PATCH_SHA256=487908875c68b8ceb3fbd2c88f04eb2ddf8dd212272a2b3898e5e4fbd885623d

RUN apk add --no-cache \
      "autoconf=2.73-r0" \
      "build-base=0.5-r4" \
      "bzip2=1.0.8-r6" \
      "libunwind-dev=1.8.3-r0" \
      "linux-headers=7.0.0-r1" \
      "patch=2.8-r0" \
      "perl=5.42.2-r0" \
    && mkdir -p /build/inputs /build/provenance /out

ADD --checksum=sha256:2db82d1e7119df3e71b7640219b6dfe84789bc0537983c3b7ac4f7189aecfeaa \
    https://github.com/jemalloc/jemalloc/releases/download/5.3.0/jemalloc-5.3.0.tar.bz2 \
    /build/inputs/jemalloc-5.3.0.tar.bz2
ADD --checksum=sha256:555b08620f00919e9b99c98a433cfcb755359395d62622cc8ae967d6717d43a0 \
    https://gitlab.alpinelinux.org/alpine/aports/-/raw/fa59839ba07b53b11d12e849222439c785125d6a/main/jemalloc/musl-exception-specification-errors.patch \
    /build/inputs/musl-exception-specification-errors.patch
ADD --checksum=sha256:487908875c68b8ceb3fbd2c88f04eb2ddf8dd212272a2b3898e5e4fbd885623d \
    https://gitlab.alpinelinux.org/alpine/aports/-/raw/fa59839ba07b53b11d12e849222439c785125d6a/main/jemalloc/pkgconf.patch \
    /build/inputs/pkgconf.patch

RUN set -eux; \
    printf '%s  %s\n' "$JEMALLOC_SOURCE_SHA256" \
      /build/inputs/jemalloc-5.3.0.tar.bz2 > /build/provenance/input-sha256.txt; \
    printf '%s  %s\n' "$MUSL_PATCH_SHA256" \
      /build/inputs/musl-exception-specification-errors.patch >> /build/provenance/input-sha256.txt; \
    printf '%s  %s\n' "$PKGCONF_PATCH_SHA256" \
      /build/inputs/pkgconf.patch >> /build/provenance/input-sha256.txt; \
    sha256sum -c -s /build/provenance/input-sha256.txt; \
    apk info -vv | sort > /build/provenance/builder-packages.txt; \
    cc --version > /build/provenance/compiler.txt; \
    ld --version > /build/provenance/linker.txt; \
    tar --extract --bzip2 --file /build/inputs/jemalloc-5.3.0.tar.bz2 --directory /build; \
    cd /build/jemalloc-5.3.0; \
    patch --strip=1 < /build/inputs/musl-exception-specification-errors.patch; \
    patch --strip=1 < /build/inputs/pkgconf.patch; \
    ./autogen.sh \
      --enable-xmalloc \
      --enable-prof \
      --enable-prof-libunwind \
      --disable-prof-libgcc \
      --disable-prof-gcc \
      --enable-stats \
      --enable-shared \
      --prefix=/opt/cybercontrol/jemalloc-prof \
      --localstatedir=/var \
      --sysconfdir=/etc \
      --with-lg-page=12 \
      --with-lg-hugepage=21 \
      | tee /build/provenance/configure-summary.txt; \
    cp config.log /build/provenance/config.log; \
    make -j"$(getconf _NPROCESSORS_ONLN)"

FROM jemalloc-compiled AS jemalloc-tested

RUN set -eux; \
    printf '%s\n' \
      'GCC 15 -O3 removes calls that intentionally violate aligned_alloc preconditions; upstream tests use -fno-builtin-aligned_alloc.' \
      > /build/provenance/upstream-test-compiler-flags.txt; \
    cd /build/jemalloc-5.3.0; \
    if ! make -j2 EXTRA_CFLAGS=-fno-builtin-aligned_alloc check \
      > /build/provenance/upstream-tests.txt 2>&1; then \
         cat /build/provenance/upstream-tests.txt; \
         exit 1; \
    fi; \
    cat /build/provenance/upstream-tests.txt

RUN set -eux; \
    cd /build/jemalloc-5.3.0; \
    make DESTDIR=/out install; \
    install -D -m 0644 COPYING \
      /out/opt/cybercontrol/jemalloc-prof/share/licenses/jemalloc/COPYING; \
    rm -rf \
      /out/opt/cybercontrol/jemalloc-prof/include \
      /out/opt/cybercontrol/jemalloc-prof/lib/*.a \
      /out/opt/cybercontrol/jemalloc-prof/lib/pkgconfig \
      /out/opt/cybercontrol/jemalloc-prof/share/doc \
      /out/opt/cybercontrol/jemalloc-prof/share/man; \
    cp -R /build/provenance \
      /out/opt/cybercontrol/jemalloc-prof/share/build-provenance; \
    sha256sum /out/opt/cybercontrol/jemalloc-prof/lib/libjemalloc.so.2 \
      > /out/opt/cybercontrol/jemalloc-prof/share/build-provenance/library-sha256.txt; \
    readelf -n /out/opt/cybercontrol/jemalloc-prof/lib/libjemalloc.so.2 \
      > /out/opt/cybercontrol/jemalloc-prof/share/build-provenance/library-notes.txt

COPY tests/load/jemalloc-profile-cohort.c /build/jemalloc-profile-cohort.c
RUN cc -shared -fPIC -g -O0 -fno-omit-frame-pointer -Wl,--build-id=sha1 \
      -o /out/opt/cybercontrol/jemalloc-prof/lib/libprofile-cohort.so \
      /build/jemalloc-profile-cohort.c \
    && readelf -n /out/opt/cybercontrol/jemalloc-prof/lib/libprofile-cohort.so \
      > /out/opt/cybercontrol/jemalloc-prof/share/build-provenance/cohort-library-notes.txt \
    && sha256sum /build/jemalloc-profile-cohort.c \
      > /out/opt/cybercontrol/jemalloc-prof/share/build-provenance/cohort-source-sha256.txt

FROM ${BACKEND_IMAGE} AS runtime

ARG CYBERCONTROL_SOURCE_SHA=unknown
ARG CYBERCONTROL_SOURCE_TREE=unknown
ARG CYBERCONTROL_PRODUCT_SOURCE_SHA=unknown
ARG CYBERCONTROL_ENGINEERING_BASELINE_SHA=unknown
ARG CYBERCONTROL_PROCESS_VERSION=unknown

USER root
RUN apk add --no-cache \
      "binutils=2.45.1-r1" \
      "libunwind=1.8.3-r0" \
      "perl=5.42.2-r0"

COPY --from=jemalloc-tested /out/opt/cybercontrol/jemalloc-prof \
    /opt/cybercontrol/jemalloc-prof
COPY --chmod=0555 tests/load/gate_c/jemalloc_profile_capability.py \
    /opt/cybercontrol/jemalloc-prof/bin/capability-check

LABEL org.opencontainers.image.revision=${CYBERCONTROL_SOURCE_SHA} \
    com.cybercontrol.source-tree=${CYBERCONTROL_SOURCE_TREE} \
    com.cybercontrol.product-source=${CYBERCONTROL_PRODUCT_SOURCE_SHA} \
    com.cybercontrol.engineering-baseline=${CYBERCONTROL_ENGINEERING_BASELINE_SHA} \
    com.cybercontrol.process-version=${CYBERCONTROL_PROCESS_VERSION} \
    com.cybercontrol.diagnostic-capability=jemalloc-prof-5.3.0

ENV LD_PRELOAD=/opt/cybercontrol/jemalloc-prof/lib/libjemalloc.so.2 \
    MALLOC_CONF=background_thread:true,dirty_decay_ms:1000,muzzy_decay_ms:1000,narenas:1,retain:false,prof:true,prof_active:false,lg_prof_sample:19,prof_accum:false,prof_gdump:false,prof_final:false,prof_leak:false

USER 10001:10001
