#!/usr/bin/env python3
"""
NoodleMat-DL: A simple and secure video downloader for pvvstream.pro hosted content.
"""

import argparse
import html
import json
import os
import re
import signal
import subprocess
import sys
import unicodedata
from typing import Optional

import requests

# --- Constants ---
MAT6TUBE_DOMAIN = "mat6tube.com"
PVV_STREAM_PATTERN = r"window\.playlist = ({.*?});"
DIRECT_MP4_PATTERN = r'(https://.*?\.mp4.*?)'
DOWNLOAD_URL_PATTERN = r'downloadUrl="([^"]+)"'


def signal_handler(sig, frame) -> None:
    """Gracefully handle Ctrl+C."""
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


def sanitize_filename(title: str) -> str:
    """
    Cleans up a string to be used as a safe filename across Windows, Linux, and macOS.
    """
    title = html.unescape(title)
    title = unicodedata.normalize('NFKC', title)
    title = re.sub(r'\s*-\s*BEST\s+XXX\s+TUBE\s*$', '', title, flags=re.IGNORECASE)

    if "://" in title:
        title = [p for p in title.split("/") if p][-1]
    elif "/" in title or "\\" in title:
        title = re.split(r'[\\/]', title)[-1]

    cleaned = [
        char for char in title 
        if unicodedata.category(char)[0] in 'LNM' or char in " _-.,"
    ]
    title = "".join(cleaned).strip().strip('.')

    reserved_names = {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    }
    if title.upper() in reserved_names:
        title += "_video"

    title = title or "video"
    while len(title.encode('utf-8')) > 200:
        title = title[:-1]

    return title


class NoodleDownloader:
    """Handles extraction and downloading using requests and aria2c."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/110.0.0.0 Safari/537.36"
            )
        })

    def _get_playlist_from_content(self, content: str) -> Optional[dict]:
        match = re.search(PVV_STREAM_PATTERN, content)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    def _extract_video_url(self, playlist: dict) -> Optional[str]:
        best_quality = -1
        video_url = None
        for source in playlist.get('sources', []):
            label = str(source.get('label', '0')).replace('p', '')
            if label.isdigit():
                quality = int(label)
                if quality > best_quality:
                    best_quality = quality
                    video_url = source.get('file')
        return video_url

    def download(self, url: str, output_dir: Optional[str] = None) -> None:
        url = url.replace("noodlemagazine.com", MAT6TUBE_DOMAIN).replace("noodle.yemoja.xyz", MAT6TUBE_DOMAIN)

        try:
            print(f"[*] Fetching page content: {url}")
            page_content = self.session.get(url).text
            video_url = None

            playlist = self._get_playlist_from_content(page_content)
            
            if not playlist:
                dl_match = re.search(DOWNLOAD_URL_PATTERN, page_content)
                if dl_match:
                    print("[*] Main playlist missing. Attempting fallback to download page...")
                    dl_url = f"https://{MAT6TUBE_DOMAIN}{dl_match.group(1)}"
                    dl_content = self.session.get(dl_url, headers={'Referer': url}).text
                    playlist = self._get_playlist_from_content(dl_content)

            if playlist:
                video_url = self._extract_video_url(playlist)
            else:
                mp4_match = re.search(DIRECT_MP4_PATTERN, page_content)
                if mp4_match:
                    video_url = mp4_match.group(1)

            if not video_url:
                print("[-] Error: Could not find a valid video URL.")
                return

            title_match = re.search(r'<title>(.+?)</title>', page_content)
            title = title_match.group(1) if title_match else ""
            sanitized_name = sanitize_filename(title)
            
            if not sanitized_name:
                id_match = re.search(r'/watch/([-_\d]+)', url)
                sanitized_name = id_match.group(1) if id_match else "video"
            
            sanitized_name += ".mp4"
            output_path = os.path.join(os.path.abspath(output_dir or "."), sanitized_name)
            
            if os.path.exists(output_path) and not os.path.exists(output_path + ".aria2"):
                print(f"[+] Video has already been downloaded: {sanitized_name}")
                return
            
            if os.path.exists(output_path + ".noodle"):
                print(f"[*] This download was started with the native downloader. Please use NoodleMat-experimental.py with --native to continue.")
                return

            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            print(f"[+] Found Video: {sanitized_name}")
            
            # Note: aria2c is required because requests is blocked by the CDN's TLS protection
            command = [
                "aria2c", "-c", "-j", "16", "-s", "16", "-x", "16", "-k", "1M",
                f'--header=Referer: {url}',
                "-d", os.path.dirname(output_path),
                "-o", os.path.basename(output_path),
                video_url
            ]

            try:
                subprocess.run(command, check=True)
                print(f"[+] Successfully downloaded: {sanitized_name}")
            except subprocess.CalledProcessError as e:
                print(f"[-] Download failed (aria2c exit code: {e.returncode})")
            except FileNotFoundError:
                print("[-] Error: aria2c not found. Please install aria2 (e.g., 'pkg install aria2' on Termux).")
            except KeyboardInterrupt:
                pass

        except Exception as e:
            print(f"[-] An unexpected error occurred: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="NoodleMat-DL: Professional video downloader for pvvstream content."
    )
    parser.add_argument("url", help="The URL of the video to download.")
    parser.add_argument("-o", "--output", help="The directory to save the video.", default=None)
    
    args = parser.parse_args()
    NoodleDownloader().download(args.url, args.output)


if __name__ == "__main__":
    main()
