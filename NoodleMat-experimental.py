#!/usr/bin/env python3
"""
NoodleMat-Experimental: Advanced Noodle/Mat6 downloader with aria2c RPC and progress bar.
"""

import argparse
import html
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Dict, List, Any

import requests

# Optional curl_cffi for Cloudflare bypass on non-Termux systems
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

# --- ANSI Constants ---
CLR_RESET = "\033[0m"
CLR_RED = "\033[91m"
CLR_GREEN = "\033[92m"
CLR_YELLOW = "\033[93m"
CLR_BLUE = "\033[94m"
CLR_CYAN = "\033[96m"

# --- Global State for Signal Handling ---
class GlobalState:
    is_shutting_down = False
    current_downloader = None
    active_gid = None

state = GlobalState()

def signal_handler(sig, frame) -> None:
    """Handles Ctrl+C and termination signals gracefully."""
    if state.is_shutting_down:
        return
    state.is_shutting_down = True
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    sys.stdout.write(f"\n{CLR_YELLOW}[!] Shutdown signal received. Performing safety cleanup...{CLR_RESET}\n")
    if state.current_downloader:
        state.current_downloader.handle_shutdown()
    sys.stdout.write(f"{CLR_GREEN}[+] Cleanup complete. Safe to exit.{CLR_RESET}\n")
    os._exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

def sanitize_filename(title: str) -> str:
    title = html.unescape(title)
    title = unicodedata.normalize('NFKC', title)
    title = re.sub(r'\s*-\s*BEST\s+XXX\s+TUBE\s*$', '', title, flags=re.IGNORECASE)
    if "://" in title:
        parts = [p for p in title.split("/") if p]
        if len(parts) > 1: title = parts[-1]
    elif "/" in title or "\\" in title:
        if title.count("/") > 1 or title.count("\\") > 1 or title.startswith("/") or title.startswith("\\"):
            title = re.split(r'[\\/]', title)[-1]
    cleaned = [c for c in title if unicodedata.category(c)[0] in 'LNM' or c in " _-.,"]
    title = "".join(cleaned).strip().strip('.')
    reserved = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
    if title.upper() in reserved: title += "_video"
    title = title or "video"
    while len(title.encode('utf-8')) > 200: title = title[:-1]
    return title

class Aria2Downloader:
    """Aria2c RPC based downloader."""
    
    def __init__(self, port: int = 6813):
        self.port = port
        self.rpc_url = f"http://localhost:{port}/jsonrpc"
        self.process = None

    def start_server(self) -> bool:
        try:
            requests.get(self.rpc_url, timeout=1)
            print(f"[*] aria2c RPC server already running on port {self.port}")
            return True
        except:
            print(f"[*] Starting aria2c RPC server on port {self.port}...")
            self.process = subprocess.Popen(
                ["aria2c", "--enable-rpc", "--rpc-listen-all=false", f"--rpc-listen-port={self.port}", "--quiet=true"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            for _ in range(10):
                time.sleep(0.5)
                try:
                    requests.get(self.rpc_url, timeout=1)
                    return True
                except: continue
        return False

    def stop_server(self):
        if self.process:
            self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired: self.process.kill()

    def rpc_call(self, method: str, params: List = None) -> Any:
        payload = {"jsonrpc": "2.0", "id": "noodle", "method": method, "params": params or []}
        try:
            response = requests.post(self.rpc_url, json=payload, timeout=10)
            response.raise_for_status()
            return response.json().get('result')
        except Exception as e:
            if not state.is_shutting_down:
                sys.stdout.write(f"{CLR_RED}[!] RPC Error ({method}): {e}{CLR_RESET}\n")
            return None

    def handle_shutdown(self):
        if state.active_gid:
            sys.stdout.write(f"{CLR_BLUE}[*] Pausing aria2c download (GID: {state.active_gid})...{CLR_RESET}\n")
            self.rpc_call("aria2.pause", [state.active_gid])
        self.stop_server()

    def _format_size(self, size: int) -> str:
        size = float(size)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024: return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"

    def download(self, video_url: str, output_path: str, headers: Dict):
        state.current_downloader = self
        options = {
            "dir": os.path.dirname(output_path),
            "out": os.path.basename(output_path),
            "header": [f"{k}: {v}" for k, v in headers.items()],
            "continue": "true", "max-connection-per-server": "16", "split": "16", "min-split-size": "1M"
        }
        state.active_gid = self.rpc_call("aria2.addUri", [[video_url], options])
        print(f"{CLR_BLUE}[*] Download started (GID: {state.active_gid}){CLR_RESET}")
        
        try:
            while not state.is_shutting_down:
                status = self.rpc_call("aria2.tellStatus", [state.active_gid])
                if not status: break
                
                state_str = status.get('status')
                total = int(status.get('totalLength', 0))
                completed = int(status.get('completedLength', 0))
                speed = int(status.get('downloadSpeed', 0))
                
                if total > 0:
                    self._print_progress(completed, total, speed)
                
                if state_str == 'complete':
                    sys.stdout.write(f"\n{CLR_GREEN}[+] Download completed: {output_path}{CLR_RESET}\n")
                    state.active_gid = None
                    break
                elif state_str == 'error':
                    sys.stdout.write(f"\n{CLR_RED}[!] Download error occurred.{CLR_RESET}\n")
                    state.active_gid = None
                    break
                time.sleep(0.5)
        except Exception as e:
            if not state.is_shutting_down:
                print(f"\n{CLR_RED}[!] Error: {e}{CLR_RESET}")

    def _print_progress(self, completed: int, total: int, speed: int):
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        percent = (completed / total) * 100
        bar_len = max(10, cols - 60)
        filled = int(bar_len * completed // total)
        bar = '█' * filled + '░' * (bar_len - filled)
        sys.stdout.write(f"\r\033[K{CLR_BLUE}[*] Progress:{CLR_RESET} [{CLR_GREEN}{bar}{CLR_RESET}] {CLR_YELLOW}{percent:.1f}%{CLR_RESET} | {CLR_CYAN}{self._format_size(speed)}/s{CLR_RESET} | {self._format_size(completed)}/{self._format_size(total)}")
        sys.stdout.flush()

class NativeDownloader:
    """Pure-python multi-threaded downloader fallback."""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.completed_bytes = 0
        self.total_bytes = 0
        self.downloaded_session = 0
        self.segments = []
        self.state_file = ""
        self.part_path = ""
        self.referer = ""

    def handle_shutdown(self):
        self.save_state()

    def _format_size(self, size: float) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024: return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"

    def save_state(self):
        if not self.state_file or self.total_bytes == 0: return
        try:
            with open(self.state_file, 'w') as f:
                json.dump({"total_bytes": self.total_bytes, "segments": self.segments}, f)
        except: pass

    def _download_segment(self, url: str, index: int):
        seg = self.segments[index]
        remaining = (seg['end'] - seg['start'] + 1) - seg['completed']
        if remaining <= 0: return
        
        start = seg['start'] + seg['completed']
        headers = {'Range': f'bytes={start}-{seg["end"]}', 'Referer': self.referer}
        
        r = None
        try:
            # Use curl_cffi if available, otherwise fallback to requests
            lib = curl_requests if HAS_CURL_CFFI else requests
            kwargs = {"impersonate": "chrome"} if HAS_CURL_CFFI else {}
            
            r = lib.get(url, headers=headers, stream=True, timeout=30, **kwargs)
            
            if r.status_code == 200 and self.total_bytes > 0:
                r.close()
                return
                
            with open(self.part_path, 'r+b') as f:
                f.seek(start)
                for chunk in r.iter_content(chunk_size=128*1024):
                    if state.is_shutting_down: break
                    if chunk:
                        write_size = min(len(chunk), remaining)
                        f.write(chunk[:write_size])
                        with self.lock:
                            self.segments[index]['completed'] += write_size
                            self.completed_bytes += write_size
                            self.downloaded_session += write_size
                        remaining -= write_size
                        if remaining <= 0: break
        except: pass
        finally:
            if r: r.close()

    def download(self, video_url: str, output_path: str, referer: str):
        state.current_downloader = self
        self.referer = referer
        self.part_path, self.state_file = output_path + ".part", output_path + ".noodle"
        
        if os.path.exists(output_path):
            print(f"{CLR_GREEN}[+] File already fully downloaded: {output_path}{CLR_RESET}")
            return

        print(f"{CLR_BLUE}[*] Using native multi-threaded downloader...{CLR_RESET}")
        try:
            lib = curl_requests if HAS_CURL_CFFI else requests
            kwargs = {"impersonate": "chrome"} if HAS_CURL_CFFI else {}
            
            r = lib.get(video_url, stream=True, timeout=15, allow_redirects=True, referer=self.referer, **kwargs)
            
            if r.status_code == 403 and not HAS_CURL_CFFI:
                print(f"{CLR_RED}[!] Cloudflare blocked the native downloader (403 Forbidden).")
                print(f"{CLR_YELLOW}[*] Please install aria2 (e.g., 'pkg install aria2' on Termux) to continue.{CLR_RESET}")
                r.close()
                return
                
            r.raise_for_status()
            self.total_bytes = int(r.headers.get('content-length', 0))
            accept_ranges = r.headers.get('accept-ranges', '').lower() == 'bytes' or r.status_code == 206
            r.close()
            
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            
            if self.total_bytes > 0:
                if shutil.disk_usage(os.path.dirname(output_path) or '.').free < self.total_bytes:
                    print(f"{CLR_RED}[!] Error: Not enough disk space.{CLR_RESET}"); return

            # Resume Logic
            if os.path.exists(self.state_file) and os.path.exists(self.part_path):
                try:
                    with open(self.state_file, 'r') as f:
                        saved = json.load(f)
                        if saved.get('total_bytes') == self.total_bytes:
                            self.segments = saved.get('segments', [])
                            self.completed_bytes = sum(s['completed'] for s in self.segments)
                            print(f"{CLR_BLUE}[*] State file found. Resuming...{CLR_RESET}")
                except: pass

            if not self.segments and self.total_bytes > 0:
                num_threads = 16
                chunk_size = self.total_bytes // num_threads
                for i in range(num_threads):
                    s = i * chunk_size
                    e = ((i + 1) * chunk_size) - 1 if i < num_threads - 1 else self.total_bytes - 1
                    self.segments.append({"start": s, "end": e, "completed": 0})
                with open(self.part_path, 'wb') as f: f.truncate(self.total_bytes)
                self.save_state()
            
            start_time = time.time()
            last_save_time = time.time()
            if accept_ranges and self.total_bytes > 0:
                with ThreadPoolExecutor(max_workers=len(self.segments)) as executor:
                    futures = [executor.submit(self._download_segment, video_url, i) for i in range(len(self.segments))]
                    while not state.is_shutting_down:
                        curr = time.time()
                        if curr - last_save_time >= 30:
                            self.save_state()
                            last_save_time = curr
                        elapsed = curr - start_time
                        speed = self.downloaded_session / elapsed if elapsed > 0 else 0
                        self._print_progress(self.completed_bytes, self.total_bytes, speed)
                        if all(f.done() for f in futures): break
                        time.sleep(0.5)
            else: self._single_thread(video_url)

            self.save_state()
            if not state.is_shutting_down and self.completed_bytes >= self.total_bytes:
                if os.path.exists(self.state_file): os.remove(self.state_file)
                os.rename(self.part_path, output_path)
                sys.stdout.write(f"\n{CLR_GREEN}[+] Download completed: {output_path}{CLR_RESET}\n")
        except Exception as e:
            if not state.is_shutting_down: print(f"\n{CLR_RED}[!] Native error: {e}{CLR_RESET}")

    def _single_thread(self, url):
        print(f"{CLR_YELLOW}[*] Single-threaded mode.{CLR_RESET}")
        r = None
        try:
            lib = curl_requests if HAS_CURL_CFFI else requests
            kwargs = {"impersonate": "chrome"} if HAS_CURL_CFFI else {}
            r = lib.get(url, stream=True, timeout=30, referer=self.referer, **kwargs)
            r.raise_for_status()
            mode = 'ab' if os.path.exists(self.part_path) else 'wb'
            with open(self.part_path, mode) as f:
                for chunk in r.iter_content(chunk_size=128*1024):
                    if state.is_shutting_down: break
                    if chunk:
                        f.write(chunk)
                        self.completed_bytes += len(chunk)
                        self.downloaded_session += len(chunk)
        except Exception as e:
             if not state.is_shutting_down: print(f"\n{CLR_RED}[!] Single-thread error: {e}{CLR_RESET}")
        finally:
            if r: r.close()

    def _print_progress(self, completed: int, total: int, speed: float):
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        percent = (completed / total) * 100
        bar_len = max(10, cols - 60)
        filled = int(bar_len * completed // total)
        bar = '█' * filled + '░' * (bar_len - filled)
        sys.stdout.write(f"\r\033[K{CLR_BLUE}[*] Progress:{CLR_RESET} [{CLR_GREEN}{bar}{CLR_RESET}] {CLR_YELLOW}{percent:.1f}%{CLR_RESET} | {CLR_CYAN}{self._format_size(speed)}/s{CLR_RESET} | {self._format_size(completed)}/{self._format_size(total)}")
        sys.stdout.flush()

class NoodleExperimental:
    def __init__(self, force_native: bool = False):
        self.force_native = force_native

    def run(self, url: str, output_dir: str = None):
        url = url.replace("noodlemagazine.com", "mat6tube.com").replace("noodle.yemoja.xyz", "mat6tube.com")
        try:
            page = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}).text
            video_url, playlist_json = None, re.search(r'window\.playlist = ({.*?});', page)
            
            if not playlist_json:
                dl_match = re.search(r'downloadUrl="([^"]+)"', page)
                if dl_match:
                    page = requests.get(f"https://mat6tube.com{dl_match.group(1)}", headers={'Referer': url, 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}).text
                    playlist_json = re.search(r'window\.playlist = ({.*?});', page)

            if playlist_json:
                playlist = json.loads(playlist_json.group(1))
                best = -1
                for s in playlist.get('sources', []):
                    q = int(str(s.get('label', '0')).replace('p', ''))
                    if q > best: best, video_url = q, s.get('file')
            
            if not video_url:
                v_match = re.search(r'(https://.*?\.mp4.*?)', page)
                if v_match: video_url = v_match.group(1)

            if video_url:
                title_match = re.search(r'<title>(.+?)</title>', page)
                title = title_match.group(1) if title_match else ""
                sanitized = sanitize_filename(title)
                if not sanitized:
                    id_match = re.search(r'/watch/([-_\d]+)', url)
                    sanitized = id_match.group(1) if id_match else "video"
                sanitized += ".mp4"
                output_path = os.path.join(os.path.abspath(output_dir or "."), sanitized)
                
                aria_file = output_path + ".aria2"
                noodle_file = output_path + ".noodle"

                if os.path.exists(output_path) and not os.path.exists(aria_file) and not os.path.exists(noodle_file):
                    print(f"{CLR_GREEN}[+] Video has already been downloaded: {sanitized}{CLR_RESET}")
                    return

                use_aria = not self.force_native and shutil.which("aria2c")
                
                if os.path.exists(aria_file) and not use_aria:
                    print(f"{CLR_YELLOW}[!] This download was started with aria2c. Please run without --native to continue.{CLR_RESET}")
                    return
                if os.path.exists(noodle_file) and use_aria:
                    print(f"{CLR_YELLOW}[!] This download was started with the native downloader. Please run with --native to continue.{CLR_RESET}")
                    return

                print(f"[*] Found Video: {title}")
                if use_aria:
                    headers = {"Referer": url, "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36'}
                    dl = Aria2Downloader(); dl.start_server(); dl.download(video_url, output_path, headers)
                else:
                    NativeDownloader().download(video_url, output_path, url)
            else: print("[-] Could not find video URL.")
        except Exception as e: print(f"[-] Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NoodleMat-Experimental: Advanced downloader.")
    parser.add_argument("url", help="Target URL.")
    parser.add_argument("-o", "--output", help="Output directory.", default=None)
    parser.add_argument("--native", action="store_true", help="Force native downloader.")
    args = parser.parse_args()
    NoodleExperimental(args.native).run(args.url, args.output)
