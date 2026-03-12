# 🍜 Noodle Magazine / Mat6Tube Downloader

![License](https://img.shields.io/badge/license-BSD--2--Clause-blue.svg)
![Python Version](https://img.shields.io/badge/python-3.x-brightgreen.svg)

A simple and efficient script to download videos from NoodleMagazine and Mat6Tube.


---

## 🛠️ Prerequisites

Before you begin, ensure you have the following installed:

-   **Python 3**
-   **aria2c**: A command-line download utility. (Optional in the experimental script)

Install the required Python packages:

```bash
pip install -r requirements.txt
```

---

## 🚀 Usage

### Standard Version
Simple and stable command-line interface.

```bash
python NoodleMat-DL.py <URL> [-o /path/to/output]
```

### Experimental Version

 Uses RPC for aria2c for a consistent download UI. As well as introduces a robust Native downloader as fallback. (Can be forced using the --native flag)

### Examples

> **Download to current directory:**

```bash
python NoodleMat-DL.py https://mat6tube.com/watch/-123456789
```

> **Experimental script usage:**

```bash
python NoodleMat-experimental.py https://mat6tube.com/watch/-123456789
```

> **Force the experimental native downloader:**

```bash
python NoodleMat-experimental.py --native https://mat6tube.com/watch/-123456789
```

---

## 📜 License

This project is licensed under the 2-Clause BSD License. See the [LICENSE](LICENSE) file for details.
