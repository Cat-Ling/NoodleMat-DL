# 🍜 Noodle Magazine / Mat6Tube Downloader

![License](https://img.shields.io/badge/license-BSD--2--Clause-blue.svg)
![Python Version](https://img.shields.io/badge/python-3.x-brightgreen.svg)

A simple and efficient script to download videos from Noodle Magazine, Mat6Tube, and their proxy websites.

---

## 🌟 Features

-   Downloads from NoodleMagazine and Mat6Tube URLs.
-   Automatically selects the best available video quality.
-   Uses `aria2c` for fast and reliable downloads.
-   Option to specify a custom output directory.

---

## 🛠️ Prerequisites

Before you begin, ensure you have the following installed:

-   **Python 3**
-   **aria2c**: A command-line download utility.


You can install the required Python packages using pip:

```bash
pip install requests
```

---

## 🚀 Usage

To download a video, simply run the script with the video URL:

```bash
python NoodleMat-DL.py <URL>
```

### Options

-   `-o, --output <DIRECTORY>`: Specify a directory to save the downloaded video.

### Examples

> **Download a video to the current directory:**

```bash
python NoodleMat-DL.py https://noodlemagazine.com/watch/-123456789
```

> **Download a video to a specific directory:**

```bash
python NoodleMat-DL.py https://noodlemagazine.com/watch/-1123456789 -o /path/to/your/videos
```

---

## ⚙️ How It Works

The script fetches the video page, extracts the video playlist, and identifies the URL for the highest quality video stream. It then invokes `aria2c` with the necessary cookies and headers to download the video efficiently.

---

## 🤝 Contributing

Contributions, issues, and feature requests are welcome! Feel free to check the [issues page](https://github.com/your-username/your-repo/issues).

---

## 📜 License

This project is licensed under the 2-Clause BSD License. See the [LICENSE](LICENSE) file for details.
