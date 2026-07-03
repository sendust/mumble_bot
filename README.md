# Mumble Audio Bot

A lightweight Python-based Mumble audio broadcaster and server management toolkit.

This project provides two utilities:

* **mbot.py** – Captures audio from an ALSA device and continuously streams it to a Mumble server.
* **mumble_manager.py** – Monitors a Mumble server, automatically manages user permissions (Mute/Suppress), and tracks channel activity.

---

# Features

## Audio Broadcaster (`mbot.py`)

* Direct ALSA audio capture
* Stereo-to-mono downmix
* Low-latency audio streaming
* Configurable audio device
* Automatic channel join
* Audio level (RMS) meter
* Compatible with Python 3.12+
* Legacy Murmur SSL compatibility patch
* Graceful shutdown

---

## Server Manager (`mumble_manager.py`)

* Monitor user join/leave events
* Monitor channel movement
* Automatically apply Mute/Suppress ACL
* Whitelist-based permission management
* Real-time logging
* Python 3.12+ compatibility

---

# Project Structure

```text
.
├── mbot.py
├── mumble_manager.py
├── config.json               # Audio bot configuration
├── config_manager.json       # Manager configuration (rename as needed)
└── README.md
```

---

# Requirements

* Python 3.10+
* ALSA
* Linux

Python packages:

```bash
pip install pymumble_py3 pyalsaaudio
```

---

# Audio Bot Configuration

Example:

```json
{
  "mumble_server": "10.10.108.51",
  "mumble_port": 64738,
  "mumble_password": "",
  "bot_name": "talk_BOT",
  "target_channel": "onair",
  "mumble_bandwidth_bps": 64000,
  "alsa_device": "hw:2,0",
  "sample_rate": 48000,
  "channels": 2,
  "chunk_size": 960
}
```

---

# Running the Audio Bot

```bash
python3 mbot.py config.json
```

The bot will:

1. Connect to the Mumble server.
2. Join the configured channel.
3. Capture audio from the configured ALSA device.
4. Downmix stereo to mono.
5. Stream audio continuously.

---

# Manager Configuration

Example:

```json
{
    "server": "10.10.108.51",
    "port": 64738,
    "su": "SuperUser",
    "supassword": "password",
    "ServerMute": [
        "T1",
        "T4",
        "talk_BOT",
        "SuperUser"
    ]
}
```

Users listed in `ServerMute` are automatically kept **Unmuted** and **Unsuppressed**.

All other users are automatically **Muted** and **Suppressed**.

---

# Running the Manager

```bash
python3 mumble_manager.py
```

The manager continuously monitors:

* User connections
* User disconnections
* Channel movements
* Server mute status
* Suppress status

---

# Audio Pipeline

```text
+-------------+
| ALSA Device |
+-------------+
       |
       v
+------------------+
| Audio Capture    |
+------------------+
       |
       v
+------------------+
| Stereo -> Mono   |
+------------------+
       |
       v
+------------------+
| Queue Buffer     |
+------------------+
       |
       v
+------------------+
| Mumble Encoder   |
+------------------+
       |
       v
+------------------+
| Mumble Server    |
+------------------+
```

---

# Compatibility

* Linux
* ALSA
* Python 3.12+
* Murmur Server
* pymumble_py3

---

# Notes

* Includes a compatibility patch for Python 3.12 SSL changes.
* Designed for long-running (24/7) operation.
* Optimized for low-latency audio broadcasting.
* Supports configurable ALSA hardware devices.

---

# License

This project is released under the MIT License.
