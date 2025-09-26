#!/usr/bin/env python3

import argparse
import requests
import re
import subprocess
import os

def download_video(url, output_directory=None):
    """
    Downloads a video from a URL that uses the pvvstream.pro video hosting.
    """
    # Replace noodlemagazine.com with mat6tube.com since they're both identical
    # except the fact that noodlemagazine fails, so we always use mat6tube urls internally.
    url = url.replace("noodlemagazine.com", "mat6tube.com")
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
            
            sanitized_title = re.sub(r'[\\/*?:">|<]',"", title) + ".mp4"

            if output_directory:
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
                "-o", output_path,
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
