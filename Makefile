CC = musl-gcc

all:
	$(CC) agent.c -o agent -I/opt/liburing-musl/include -isystem /usr/include/x86_64-linux-musl -isystem /usr/lib/gcc/x86_64-linux-gnu/$(gcc -dumpversion)/include -idirafter /usr/include/x86_64-linux-gnu -idirafter /usr/include -L/opt/liburing-musl/lib -luring -O2 -s -static

remove:
	rm agent
