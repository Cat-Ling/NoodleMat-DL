#!/usr/bin/env python3

import argparse
import requests
import re
import subprocess
import os
import html
import unicodedata
import json
import time
import sys
import shutil
import signal
import threading
from concurrent.futures import ThreadPoolExecutor

# Global reference for signal handling
current_downloader = None
active_gid = None
is_shutting_down = False

def signal_handler(sig, frame):
    """Handles Ctrl+C and termination signals gracefully without allowing interruption of cleanup."""
    global current_downloader, active_gid, is_shutting_down
    if is_shutting_down: return
    is_shutting_down = True
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if hasattr(signal, 'SIGHUP'): signal.signal(signal.SIGHUP, signal.SIG_IGN)

    sys.stdout.write("\n\033[93m[!] Shutdown signal received. Performing safety cleanup (DO NOT FORCE KILL)...\033[0m\n")
    if isinstance(current_downloader, Aria2Downloader) and active_gid:
        sys.stdout.write(f"\033[94m[*] Pausing aria2c download (GID: {active_gid}) to prevent corruption...\033[0m\n")
        try:
            current_downloader.rpc_call("aria2.pause", [active_gid])
            sys.stdout.write("\033[92m[+] aria2c state saved.\033[0m\n")
        except: sys.stdout.write("\033[91m[!] Could not contact aria2c.\033[0m\n")
    elif isinstance(current_downloader, NativeDownloader):
        sys.stdout.write("\033[94m[*] Saving native downloader state...\033[0m\n")
        current_downloader.save_state()
    sys.stdout.write("\033[92m[+] Cleanup complete. Safe to exit.\033[0m\n")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
if hasattr(signal, 'SIGHUP'): signal.signal(signal.SIGHUP, signal_handler)

def sanitize_filename(title):
    title = html.unescape(title)
    title = unicodedata.normalize('NFKC', title)
    if "://" in title:
        parts = [p for p in title.split("/") if p]
        if len(parts) > 1: title = parts[-1]
    elif "/" in title or "\\" in title:
        if title.count("/") > 1 or title.count("\\") > 1 or title.startswith("/") or title.startswith("\\"):
            title = re.split(r'[\\/]', title)[-1]
    cleaned = []
    for char in title:
        cat = unicodedata.category(char)
        if cat[0] in 'LNM': cleaned.append(char)
        elif char in " _-.,": cleaned.append(char)
    title = "".join(cleaned)
    reserved_names = {"CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"}
    if title.upper() in reserved_names: title += "_video"
    title = title.strip().strip('.')
    if not title: title = "video"
    max_bytes = 200
    while len(title.encode('utf-8')) > max_bytes: title = title[:-1]
    return title

class Aria2Downloader:
    def __init__(self, port=6813):
        self.url = f"http://localhost:{port}/jsonrpc"
        self.port = port
        self.process = None

    def start_server(self):
        try:
            requests.get(self.url, timeout=1)
            print(f"[*] aria2c RPC server already running on port {self.port}")
        except requests.exceptions.ConnectionError:
            print(f"[*] Starting aria2c RPC server on port {self.port}...")
            self.process = subprocess.Popen(
                ["aria2c", "--enable-rpc", "--rpc-listen-all=false", f"--rpc-listen-port={self.port}", "--quiet=true"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            for _ in range(10):
                time.sleep(0.5)
                try:
                    requests.get(self.url, timeout=1)
                    break
                except: continue

    def rpc_call(self, method, params=None):
        payload = {"jsonrpc": "2.0", "id": "noodle", "method": method, "params": params or []}
        response = requests.post(self.url, json=payload)
        return response.json().get('result')

    def format_size(self, size):
        size = int(size)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024: return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"

    def download(self, video_url, output_path, headers):
        global current_downloader, active_gid
        current_downloader = self
        options = {
            "dir": os.path.dirname(output_path),
            "out": os.path.basename(output_path),
            "header": [f"{k}: {v}" for k, v in headers.items()],
            "continue": "true", "max-connection-per-server": "16", "split": "16", "min-split-size": "1M"
        }
        active_gid = self.rpc_call("aria2.addUri", [[video_url], options])
        print(f"\033[94m[*] Download started (GID: {active_gid})\033[0m")
        try:
            while True:
                if is_shutting_down: break
                status = self.rpc_call("aria2.tellStatus", [active_gid])
                if not status: break
                state = status.get('status')
                total = int(status.get('totalLength', 0))
                completed = int(status.get('completedLength', 0))
                speed = int(status.get('downloadSpeed', 0))
                if total > 0:
                    cols, _ = shutil.get_terminal_size(fallback=(80, 24))
                    percent = (completed / total) * 100
                    prefix, suffix = f"[*] Progress: [", f"] {percent:.1f}% | {self.format_size(speed)}/s | {self.format_size(completed)}/{self.format_size(total)}"
                    bar_len = max(10, cols - len(prefix) - len(suffix) - 5)
                    filled_len = int(bar_len * completed // total)
                    bar = '█' * filled_len + '░' * (bar_len - filled_len)
                    sys.stdout.write(f"\r\033[K\033[94m[*] Progress:\033[0m [\033[92m{bar}\033[0m] \033[93m{percent:.1f}%\033[0m | \033[96m{self.format_size(speed)}/s\033[0m | {self.format_size(completed)}/{self.format_size(total)}")
                    sys.stdout.flush()
                if state == 'complete':
                    sys.stdout.write(f"\n\033[92m[+] Download completed: {output_path}\033[0m\n")
                    active_gid = None
                    break
                elif state == 'error':
                    sys.stdout.write(f"\n\033[91m[!] Download error occurred.\033[0m\n")
                    active_gid = None
                    break
                time.sleep(0.5)
        except SystemExit: raise
        except Exception as e:
            if not is_shutting_down:
                if active_gid: self.rpc_call("aria2.pause", [active_gid])
                print(f"\n\033[91m[!] Error: {e}\033[0m")

class NativeDownloader:
    def __init__(self):
        self.lock = threading.Lock()
        self.completed_bytes = 0
        self.total_bytes = 0
        self.start_time = 0
        self.downloaded_this_session = 0
        self.segments = []
        self.state_file = ""
        self.part_path = ""

    def format_size(self, size):
        size = float(size)
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024: return f"{size:.2f} {unit}"
            size /= 1024
        return f"{size:.2f} PB"

    def save_state(self):
        if not self.state_file or self.total_bytes == 0: return
        state = {"total_bytes": self.total_bytes, "segments": self.segments}
        try:
            with open(self.state_file, 'w') as f: json.dump(state, f)
        except: pass

    def download_segment(self, url, headers, index, output_path):
        seg = self.segments[index]
        start = seg['start'] + seg['completed']
        end = seg['end']
        if start > end: return
        segment_headers = {**headers, 'Range': f'bytes={start}-{end}'}
        try:
            with requests.get(url, headers=segment_headers, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(output_path, 'r+b') as f:
                    f.seek(start)
                    for chunk in r.iter_content(chunk_size=1024*1024):
                        if is_shutting_down: return
                        if chunk:
                            f.write(chunk)
                            with self.lock:
                                self.segments[index]['completed'] += len(chunk)
                                self.completed_bytes += len(chunk)
                                self.downloaded_this_session += len(chunk)
        except Exception as e:
            if not is_shutting_down: sys.stdout.write(f"\n\033[91m[!] Thread {index} error: {e}\033[0m\n")

    def download(self, video_url, output_path, headers, is_fallback=True):
        global current_downloader
        current_downloader = self
        self.part_path = output_path + ".part"
        self.state_file = output_path + ".noodle"
        
        if os.path.exists(output_path):
            print(f"\033[92m[+] File already fully downloaded: {output_path}\033[0m")
            return

        print(f"\033[94m[*] Using native multi-threaded downloader (Requests)...\033[0m")
        try:
            head = requests.head(video_url, headers=headers, timeout=15, allow_redirects=True)
            self.total_bytes = int(head.headers.get('content-length', 0))
            accept_ranges = head.headers.get('accept-ranges', 'none').lower() == 'bytes' or head.status_code == 206
            
            if self.total_bytes == 0:
                print("\033[91m[!] Size unknown. Multi-threading disabled.\033[0m")
                accept_ranges = False

            dir_name = os.path.dirname(os.path.abspath(output_path))
            if dir_name: os.makedirs(dir_name, exist_ok=True)
            
            # SAFETY CHECK: Disk Space
            try:
                usage = shutil.disk_usage(dir_name)
                if usage.free < self.total_bytes:
                    print(f"\033[91m[!] Error: Not enough disk space. Required: {self.format_size(self.total_bytes)}, Free: {self.format_size(usage.free)}\033[0m")
                    return
            except: pass

            # SELF-HEALING
            if os.path.exists(self.part_path) and not os.path.exists(self.state_file):
                print(f"\033[93m[*] Found .part file without state map. Restarting to ensure integrity...\033[0m")
                os.remove(self.part_path)

            # Resume Logic
            if os.path.exists(self.state_file) and os.path.exists(self.part_path):
                try:
                    with open(self.state_file, 'r') as f:
                        saved = json.load(f)
                        if saved.get('total_bytes') == self.total_bytes:
                            self.segments = saved.get('segments', [])
                            self.completed_bytes = sum(s['completed'] for s in self.segments)
                            print(f"\033[94m[*] State file found. Resuming from {self.format_size(self.completed_bytes)}...\033[0m")
                except: pass

            if not self.segments and self.total_bytes > 0:
                num_threads = 16
                chunk_size = self.total_bytes // num_threads
                for i in range(num_threads):
                    start = i * chunk_size
                    end = ((i + 1) * chunk_size) - 1 if i < num_threads - 1 else self.total_bytes - 1
                    self.segments.append({"start": start, "end": end, "completed": 0})
                
                # ATOMIC INITIALIZATION: Save state then truncate
                self.save_state()
                try:
                    with open(self.part_path, 'wb') as f: f.truncate(self.total_bytes)
                except Exception as e:
                    print(f"\033[91m[!] Pre-allocation failed: {e}\033[0m")
                    return
            
            self.start_time = time.time()
            if accept_ranges and self.total_bytes > 0:
                with ThreadPoolExecutor(max_workers=len(self.segments)) as executor:
                    futures = [executor.submit(self.download_segment, video_url, headers, i, self.part_path) for i in range(len(self.segments))]
                    last_save = time.time()
                    while any(f.running() for f in futures):
                        if is_shutting_down: break
                        if time.time() - last_save > 5:
                            self.save_state()
                            last_save = time.time()
                        elapsed = time.time() - self.start_time
                        speed = self.downloaded_this_session / elapsed if elapsed > 0 else 0
                        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
                        percent = (self.completed_bytes / self.total_bytes) * 100
                        prefix, suffix = f"[*] Progress: [", f"] {percent:.1f}% | {self.format_size(speed)}/s | {self.format_size(self.completed_bytes)}/{self.format_size(self.total_bytes)}"
                        bar_len = max(10, cols - len(prefix) - len(suffix) - 5)
                        filled_len = int(bar_len * self.completed_bytes // self.total_bytes)
                        bar = '█' * filled_len + '░' * (bar_len - filled_len)
                        sys.stdout.write(f"\r\033[K\033[94m[*] Progress:\033[0m [\033[92m{bar}\033[0m] \033[93m{percent:.1f}%\033[0m | \033[96m{self.format_size(speed)}/s\033[0m | {self.format_size(self.completed_bytes)}/{self.format_size(self.total_bytes)}")
                        sys.stdout.flush()
                        time.sleep(0.5)
            else: self.download_single_thread(video_url, self.part_path, headers, self.completed_bytes)

            if not is_shutting_down:
                if self.completed_bytes >= self.total_bytes:
                    if os.path.exists(self.state_file): os.remove(self.state_file)
                    os.rename(self.part_path, output_path)
                    sys.stdout.write(f"\n\033[92m[+] Download completed: {output_path}\033[0m\n")
                else: self.save_state()
        except SystemExit: raise
        except Exception as e:
            if not is_shutting_down: sys.stdout.write(f"\n\033[91m[!] Native download error: {e}\033[0m\n")

    def download_single_thread(self, url, output_path, headers, resume_start):
        print("\033[93m[*] Single-threaded mode.\033[0m")
        mode = 'ab' if resume_start > 0 else 'wb'
        with requests.get(url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(output_path, mode) as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if is_shutting_down: break
                    if chunk:
                        f.write(chunk)
                        self.completed_bytes += len(chunk)
                        self.downloaded_this_session += len(chunk)

def download_video(url, output_directory=None, force_native=False):
    url = url.replace("noodlemagazine.com", "mat6tube.com").replace("noodle.yemoja.xyz", "mat6tube.com")
    try:
        session = requests.Session()
        ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.3029.110 Safari/537.36'
        session.headers.update({'User-Agent': ua})
        page_content = session.get(url).text
        video_url = None
        playlist_match = re.search(r'window\.playlist = ({.*?});', page_content)
        if playlist_match:
            playlist_json = playlist_match.group(1).replace('true', 'True').replace('false', 'False')
            playlist = eval(playlist_json)
            best_quality = 0
            for source in playlist['sources']:
                quality = int(source['label'].replace('p', ''))
                if quality > best_quality:
                    best_quality = quality
                    video_url = source['file']
        else:
            video_url_match = re.search(r'(https://.*?\.mp4.*?)', page_content)
            if video_url_match: video_url = video_url_match.group(1)
        if video_url:
            title_match = re.search(r'<title>(.+?)</title>', page_content)
            title = title_match.group(1) if title_match else "video"
            sanitized_title = sanitize_filename(title) + ".mp4"
            if output_directory: output_path = os.path.join(os.path.abspath(output_directory), sanitized_title)
            else: output_path = os.path.abspath(sanitized_title)
            print(f"[*] Found video URL: {video_url}\n[*] Title: {title}")
            cookies = session.cookies.get_dict()
            cookie_string = "; ".join([f"{key}={value}" for key, value in cookies.items()])
            headers = {"Cookie": cookie_string, "Referer": url, "User-Agent": ua}
            if not force_native and shutil.which("aria2c"):
                downloader = Aria2Downloader()
                downloader.start_server()
                downloader.download(video_url, output_path, headers)
            else:
                downloader = NativeDownloader()
                downloader.download(video_url, output_path, headers, is_fallback=(not force_native))
        else: print("[-] Could not find video URL.")
    except Exception as e: print(f"[-] An error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Experimental Noodle/Mat6 downloader with aria2c RPC and progress bar.")
    parser.add_argument("url", help="The URL of the video to download.")
    parser.add_argument("-o", "--output", help="The directory to download the video to.", default=None)
    parser.add_argument("--native", action="store_true", help="Force use of native downloader.")
    args = parser.parse_args()
    download_video(args.url, args.output, args.native)
