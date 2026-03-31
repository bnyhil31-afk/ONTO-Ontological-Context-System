# Setting up ONTO on Raspberry Pi

ONTO was designed with the Raspberry Pi in mind.
It runs on modest hardware, uses no cloud services, and keeps all data
on the device. A Pi running ONTO is a fully self-contained, sovereign
context system.

---

## Supported hardware

| Model | Works | Notes |
|---|---|---|
| Pi 5 | ✅ | Best performance |
| Pi 4 (any RAM) | ✅ | Recommended for production use |
| Pi 3B / 3B+ | ✅ | Good for personal use |
| Pi Zero 2W | ✅ | Works — slower startup, fine for light use |
| Pi Zero W (original) | ⚠️ | Single-core, 512MB — functional but slow |
| Pi 1 / Pi 2 | ❌ | Not supported — too slow for reliable use |

---

## What you need

- A Raspberry Pi (see above)
- A microSD card — 8GB minimum, 32GB recommended
- Power supply for your Pi model
- Internet connection for initial setup (not needed after)
- A keyboard and monitor, OR SSH access from another computer

---

## Step 1 — Prepare the SD card

Download and install the **Raspberry Pi Imager** from:  
https://www.raspberrypi.com/software/

In the Imager:
1. Choose your Pi model
2. Choose **Raspberry Pi OS (64-bit)** — the full or lite version both work
3. Choose your SD card
4. Click the settings gear — configure your username, password, Wi-Fi,
   and enable SSH if you want headless access
5. Write the image

Boot your Pi from the SD card.

---

## Step 2 — Update and install dependencies

Open a terminal on the Pi (or SSH in):

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3 python3-pip git -y
```

Verify Python:

```bash
python3 --version
```

You need Python 3.7 or higher. Raspberry Pi OS ships with a compatible
version by default.

---

## Step 3 — Clone ONTO

```bash
git clone https://github.com/bnyhil31-afk/ONTO-Ontological-Context-System.git
cd ONTO-Ontological-Context-System
```

---

## Step 4 — Set up

```bash
bash setup.sh
```

This creates the data directory and prepares the system.

---

## Step 5 — Run

```bash
python3 main.py
```

Type anything. Press Enter. Follow the prompts.

---

## Optional: Run ONTO automatically at boot

If you want ONTO to start every time the Pi powers on, create a systemd
service. This is useful for dedicated deployments.

Create the service file:

```bash
sudo nano /etc/systemd/system/onto.service
```

Paste this — replacing `YOUR_USERNAME` with your Pi username:

```
[Unit]
Description=ONTO Ontological Context System
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/ONTO-Ontological-Context-System
ExecStart=/usr/bin/python3 main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Save and enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable onto
sudo systemctl start onto
```

Check the status:

```bash
sudo systemctl status onto
```

---

## Optional: Run headlessly (no monitor or keyboard)

If your Pi is set up with SSH enabled, you can run ONTO over SSH from
any computer on the same network:

```bash
ssh YOUR_USERNAME@YOUR_PI_IP
cd ONTO-Ontological-Context-System
python3 main.py
```

Find your Pi's IP address:

```bash
hostname -I
```

---

## Physical security

A Pi running ONTO in a production context should be physically secured.

**Why this matters:**  
The threat model (T-015) identifies the "evil maid" attack — an attacker
with brief physical access can replace the SD card with a backdoored
version. The system appears to start normally but is compromised.

**What to do:**

1. **Enable full-disk encryption**  
   Raspberry Pi OS supports full-disk encryption. Set this up before
   writing any sensitive data to the device. Instructions:  
   https://www.raspberrypi.com/documentation/computers/raspberry-pi.html

2. **Physical location**  
   Keep the Pi in a locked location if possible. Treat it like the
   journal it is — it contains a permanent record of everything.

3. **SD card security**  
   Label your SD card and check it periodically. An SD card is small
   and easy to swap undetected.

These are recommendations. Your threat model may differ. The system
runs without encryption — but sensitive deployments should not.

---

## Performance notes

ONTO is designed to be efficient. On a Pi 4, it is fast.
On a Pi Zero 2W, startup takes a few seconds longer — normal operation
is fine.

If you are running other services on the same Pi (a media server,
home automation, etc.), ONTO will share resources without conflict.
It is intentionally lightweight.

---

## Verifying the principles

```bash
sha256sum principles.txt
```

Compare the output to the hash in the README.
If it matches — the principles are intact.

---

## Reading the memory

```bash
python3 -c "
import sys; sys.path.insert(0,'.')
from modules import memory
memory.initialize()
memory.print_readable(memory.read_all())
"
```

Or copy `data/memory.db` to another machine and open it with any
SQLite viewer. It is a standard, portable format.

---

## Troubleshooting

**`bash setup.sh` fails with permission error**  
```bash
chmod +x setup.sh
bash setup.sh
```

**Python version is too old**  
```bash
python3 --version
```
If below 3.7, update Raspberry Pi OS:
```bash
sudo apt update && sudo apt full-upgrade -y
```

**Out of disk space**  
```bash
df -h
```
The `data/memory.db` grows over time. Monitor disk usage on long-running
deployments. 32GB SD cards are recommended for this reason.

**SSH connection refused**  
SSH must be enabled in raspi-config:
```bash
sudo raspi-config
```
Navigate to Interface Options → SSH → Enable.

**Something else**  
Open an issue at the repository. All questions are welcome.

---

*This guide will be updated as the project evolves.*  
*If you find something wrong or unclear, open an issue.*  
*Real-world feedback from Pi deployments directly improves this guide.*
