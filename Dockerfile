# startoff with kali
FROM kalilinux/kali-rolling

#define envs
ENV DEBIAN_FRONTEND=noninteractive

# Add local dir so that we can map it externally
ADD . /agent

# Update package lists and install essential build tools and libraries
# required for kernel compilation.
RUN apt-get update && \
    apt-get install -y \
    build-essential \
    libssl-dev \
    libelf-dev \
    libcap-dev \
    git \
    vim \
    curl \
    xz-utils \
    musl-tools \
    wget && \
    rm -rf /var/lib/apt/lists/*

# Create a directory for liburing

WORKDIR /opt/liburing-src
RUN git clone https://github.com/axboe/liburing.git

WORKDIR /opt/liburing-src/liburing

RUN CC=musl-gcc \
CFLAGS="\
-isystem /usr/include/x86_64-linux-musl \
-isystem /usr/lib/gcc/x86_64-linux-gnu/$(gcc -dumpversion)/include \
-idirafter /usr/include/x86_64-linux-gnu \
-idirafter /usr/include \
" \
./configure --prefix=/opt/liburing-musl

RUN CC=musl-gcc \
CFLAGS="\
-isystem /usr/include/x86_64-linux-musl \
-isystem /usr/lib/gcc/x86_64-linux-gnu/$(gcc -dumpversion)/include \
-idirafter /usr/include/x86_64-linux-gnu \
-idirafter /usr/include \
" \
make

RUN make install

# Download the agent in /agent
WORKDIR /agent
RUN git clone https://github.com/thekeen01/RingReaper.git

# Set the entrypoint to keep the container running and allow interactive access.
# This is useful for debugging and manual compilation.
WORKDIR /agent
CMD ["bash"]
