#!/usr/bin/env python3

import argparse
import requests
import re
import subprocess
import os
import html
import unicodedata

def sanitize_filename(title):
    """
    Cleans up a string to be used as a safe filename across Windows, Linux, BSD, and macOS.
    Supports all languages while stripping unsafe characters like $, emojis, and shell-sensitive symbols.
    """
    # Unescape HTML entities (e.g., &amp; -> &)
    title = html.unescape(title)
    
    # Normalize Unicode (NFKC handles compatibility characters and unifies representations)
    title = unicodedata.normalize('NFKC', title)
    
    # If the title is a URL, try to extract the last meaningful part
    if "://" in title:
        parts = [p for p in title.split("/") if p]
        if len(parts) > 1:
            title = parts[-1]
    # If it looks like a file path (starts with / or has multiple separators), 
    # take the last part. Otherwise, we keep it as it might be part of the title.
    elif "/" in title or "\\" in title:
        if title.count("/") > 1 or title.count("\\") > 1 or title.startswith("/") or title.startswith("\\"):
            title = re.split(r'[\\/]', title)[-1]
    
    # Filter characters:
    # Keep Letters (L), Numbers (N), Marks (M) (for accents/combining chars).
    # Also keep a very limited set of safe punctuation/separators.
    # This naturally strips $, emojis, and most shell-dangerous characters.
    cleaned = []
    for char in title:
        cat = unicodedata.category(char)
        if cat[0] in 'LNM':
            cleaned.append(char)
        elif char in " _-.,":
            cleaned.append(char)
    title = "".join(cleaned)

    # Windows Reserved Names (cannot be used as filenames even with an extension)
    reserved_names = {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
    }
    if title.upper() in reserved_names:
        title += "_video"

    # Strip leading/trailing whitespace and dots (problematic on Windows)
    title = title.strip().strip('.')
    
    # Fallback for empty titles
    if not title:
        title = "video"
        
    # Enforce a safe filename length limit (200 bytes is safe for all systems).
    max_bytes = 200
    while len(title.encode('utf-8')) > max_bytes:
        title = title[:-1]
        
    return title

def download_video(url, output_directory=None):
    """
    Downloads a video from a URL that uses the pvvstream.pro video hosting.
    """
    # Replace noodlemagazine.com and noodle.yemoja.xyz with mat6tube.com since they're both identical
    # except the fact that noodlemagazine fails, so we always use mat6tube urls internally.
    url = url.replace("noodlemagazine.com", "mat6tube.com").replace("noodle.yemoja.xyz", "mat6tube.com")
    try:
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/107.0.3029.110 Safari/537.36'})

        page_content = session.get(url).text

        video_url = None

        playlist_match = re.search(r'window\.playlist = ({.*?});', page_content)

        if playlist_match:
            playlist_json = playlist_match.group(1)
            playlist_json = playlist_json.replace('true', 'True').replace('false', 'False')
            playlist = eval(playlist_json)

            best_quality = 0

            for source in playlist['sources']:
                quality = int(source['label'].replace('p', ''))
                if quality > best_quality:
                    best_quality = quality
                    video_url = source['file']
        else:
            video_url_match = re.search(r'(https://.*?\.mp4.*?)', page_content)
            if video_url_match:
                video_url = video_url_match.group(1)

        if video_url:
            referrer = url

            title_match = re.search(r'<title>(.+?)</title>', page_content)
            title = title_match.group(1) if title_match else "video"
            
            sanitized_title = sanitize_filename(title) + ".mp4"

            if output_directory:
                if not os.path.isabs(output_directory):
                    output_directory = os.path.abspath(output_directory)
                output_path = os.path.join(output_directory, sanitized_title)
            else:
                output_path = sanitized_title

            print(f"Found video URL: {video_url}")
            print(f"Downloading video: {sanitized_title}")

            cookies = session.cookies.get_dict()
            cookie_string = "; ".join([f"{key}={value}" for key, value in cookies.items()])

            command = [
                "aria2c",
                "-c",
                "-j", "16",
                "-s", "16",
                "-x", "16",
                "-k", "1M",
                f'--header=Cookie: {cookie_string}',
                f'--header=Referer: {referrer}',
                "-d", os.path.dirname(output_path),
                "-o", os.path.basename(output_path),
                video_url
            ]

            subprocess.run(command)

            print(f"Downloaded: {sanitized_title}")
        else:
            print("Could not find video URL.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download videos from websites that use the pvvstream.pro video hosting.")
    parser.add_argument("url", help="The URL of the video to download.")
    parser.add_argument("-o", "--output", help="The directory to download the video to.", default=None)
    args = parser.parse_args()

    download_video(args.url, args.output)
