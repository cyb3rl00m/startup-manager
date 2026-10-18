<div align="center">

<img src="data/icons/hicolor/scalable/apps/io.github.cyb3rl00m.StartupManager.svg" width="128" height="128" alt="Startup Manager icon">

# Startup Manager

**Choose what starts when you log in — apps, programs and your own bash commands.**

[![Release v1.0.0](https://img.shields.io/badge/release-v1.0.0-26a269)](https://github.com/cyb3rl00m/startup-manager/releases/latest)
[![License: MIT](https://img.shields.io/badge/license-MIT-3584e4)](LICENSE)
![Platform](https://img.shields.io/badge/platform-Linux-555555?logo=linux&logoColor=white)
![GTK 4 + libadwaita](https://img.shields.io/badge/GTK%204-libadwaita-4a86cf?logo=gnome&logoColor=white)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab?logo=python&logoColor=white)
[![Made with Claude](https://img.shields.io/badge/made%20with-Claude-d97757)](#credits)

[Install](#install) · [What you can manage](#what-you-can-manage) · [How it works](#how-it-works) · [FAQ](#faq) · [Credits](#credits) · [Contributing](CONTRIBUTING.md)

<br>

<img src="docs/screenshot.png" width="860" alt="Startup Manager listing the apps that start at login, each with an on/off switch">

</div>

<br>

Every Linux desktop starts a handful of things when you log in: apps you added, tray icons that
installed software slipped in, background parts of the desktop. Finding them means digging through
`~/.config/autostart` and `/etc/xdg/autostart`, and running your own script at login means writing
`.desktop` files by hand and hoping it works.

**Startup Manager puts all of it in one window** — with a switch for every entry, a picker for your
installed apps, and a place to run your own bash commands at login, with their output saved so you
can see what happened.

## Highlights

- 🚀 **Add apps in two clicks.** Pick any installed app — APT, Snap, Flatpak or local — from a
  searchable list, or start any program by its command.
- 🔘 **A switch for everything.** Pause an entry without deleting it. Turn it back on any time.
- ⏱️ **Start things later.** Give any app or command a delay so your desktop is ready first.
- 💻 **Your own bash commands.** Write as many lines as you like. A live syntax check catches typos
  *before* they reach your login.
- 📄 **See what happened.** Every command's output is saved. **Run Now** tests it without logging out.
- 🌐 **Waits for the network** if you ask it to — handy for sync and mount scripts.
- 🛡️ **Never touches system files.** Entries that installed software added for everyone are turned
  off for *your account only*, and **Restore Default** brings them back.
- ↩️ **Undo** for adding, removing and restoring.
- 🔄 **Stays in sync.** Changes made by other tools or by hand show up right away.

## What you can manage

| | Type | Example | What you can do |
|:-:|---|---|---|
| 🚀 | **Your startup apps** | Discord, Thunderbird, Steam | Add, pause, delay, edit, remove |
| ⌨️ | **Custom programs** | `syncthing --no-browser` | Add, pause, delay, edit, remove |
| 🧩 | **Added by installed software** | Cloud sync clients, printer tools | Turn off for your account, edit, restore default |
| ⚙️ | **System services** | Keyring, input methods, notifications | Turn off for your account (hidden by default, asks first) |
| 💻 | **Custom commands** | `rclone mount gdrive: ~/Drive &` | Add, pause, delay, wait for network, run now, view output |

**What the sections mean**

- **Your startup apps** — things you added. Only you see them.
- **Added by installed software** — entries in `/etc/xdg/autostart` that start for every user. You
  can't delete them (they belong to the system), but you can turn them off for yourself.
- **System services** — background parts of the desktop. They're hidden unless you turn on
  *Show System Services* in the menu, and the app asks before you turn one off.

## Install

### Ubuntu, Debian, Linux Mint, Pop!_OS — `.deb` package (recommended)

Download and install version 1.0.0:

```bash
wget https://github.com/cyb3rl00m/startup-manager/releases/download/v1.0.0/startup-manager_1.0.0_all.deb
sudo apt install ./startup-manager_1.0.0_all.deb
```

Or download **`startup-manager_1.0.0_all.deb`** by hand from the
[release page](https://github.com/cyb3rl00m/startup-manager/releases/tag/v1.0.0), open a terminal in
the folder where you saved it (usually `cd ~/Downloads`), and run the second command.

Then open **Startup Manager** from your app menu. APT installs everything it needs (GTK 4,
libadwaita and the Python bindings) automatically.

**Updating:** download the newest `.deb` from the
[releases page](https://github.com/cyb3rl00m/startup-manager/releases) and install it the same way —
it replaces the old version.

### Any distribution — from source

```bash
git clone https://github.com/cyb3rl00m/startup-manager.git
cd startup-manager
sudo bash install.sh
```

`install.sh` installs the dependencies with your package manager (APT, DNF, pacman or zypper) and
copies the app into `/usr/local` — the place for software that doesn't come from your package manager.
(Want it somewhere else? `sudo PREFIX=/opt/startup-manager bash install.sh`)

### Try it without installing

```bash
git clone https://github.com/cyb3rl00m/startup-manager.git
cd startup-manager
python3 startup-manager
```

### Uninstall

```bash
sudo apt remove startup-manager     # if you installed the .deb
sudo bash uninstall.sh              # if you used install.sh
```

Uninstalling the app does **not** remove your startup entries or commands — they keep running at
login. Turn them off in the app first if you don't want them anymore.

## How to use it

1. **Apps tab:** press **Add App** and pick an app — it will start the next time you log in.
2. **Commands tab:** press **Add Command**, type your bash commands, and press **Run Now** to test them.
3. **Flip a switch** to pause anything, or open the **⋮** menu to edit, delay or remove it.

## How it works

Startup Manager only edits the standard autostart files that every Linux desktop reads. It needs no
password, runs nothing in the background, and nothing it creates depends on it being installed.

| Rule | Why it matters |
|---|---|
| Never asks for your password and never writes outside your home folder | It can only change your own account |
| System entries in `/etc/xdg/autostart` are never edited — turning one off writes your own copy with the same name, which overrides it | Other users and package updates are unaffected |
| Turning a system entry back on deletes your copy again | Future package updates still apply |
| Custom commands are plain scripts in your home folder that only you can read or run | You can read every line that runs at login |
| Commands are checked with `bash -n` before they're saved | A typo can't silently break your login |
| Each command's output log is capped at 256 KB | A noisy command can't fill your disk |
| Everything is a standard `.desktop` autostart file | Keeps working if you uninstall the app, and other tools see the same list |

**Where things are saved**

| What | Where |
|---|---|
| Your startup entries | `~/.config/autostart/*.desktop` |
| Entries from installed software (read only) | `/etc/xdg/autostart/` |
| Custom command scripts | `~/.local/share/startup-manager/commands/*.sh` |
| Command output | `~/.local/state/startup-manager/logs/*.log` |

**Turning something off** sets `Hidden=true` and `X-GNOME-Autostart-enabled=false`, which every
desktop understands. **Delays** for apps use GNOME's `X-GNOME-Autostart-Delay`; delays for commands
are a `sleep` inside the script, so they work on every desktop.

## Compared to Startup Applications

Ubuntu's built-in **Startup Applications** tool is simple and does the basics well. Startup Manager
adds what it doesn't do:

| | Startup Manager | Startup Applications |
|---|:-:|:-:|
| Turn entries on and off | ✅ | ✅ |
| Add a program by its command | ✅ | ✅ |
| Pick from installed apps (APT, Snap, Flatpak) | ✅ | Browse for a file |
| Start delay | ✅ | — |
| Multi-line bash commands (pipes, variables, `~`) | ✅ | One command line |
| Syntax check and saved output for commands | ✅ | — |
| Restore a system entry you changed | ✅ | — |
| Show hidden system services | ✅ | — |
| Undo | ✅ | — |

<sub>Based on Startup Applications (`gnome-session-properties`) at the time of writing. Spotted
something outdated? Please open an issue — a fair comparison matters.</sub>

## Supported systems

Built for **Ubuntu 26.04 LTS**. Works on any distribution with GTK 4 and libadwaita 1.5 or newer:
Ubuntu 24.04+, Debian 13, Linux Mint 22, Pop!_OS 24.04, Zorin OS 18, elementary OS 8, Fedora 40+,
Arch, openSUSE Tumbleweed and more.

The entries it creates work on every desktop that follows the freedesktop autostart standard —
GNOME, Cinnamon, MATE, Xfce, KDE Plasma, Budgie, LXQt and COSMIC. Two features depend on your system:

- **Start delay for apps** works on GNOME and Cinnamon. Other desktops start the app right away.
  (Delays for custom commands work everywhere.)
- **Wait for network** uses NetworkManager's `nm-online`, which most desktop distributions have.

## FAQ

<details>
<summary><b>Does it run in the background?</b></summary>

No. It does nothing until you open it. Your desktop itself starts the entries at login — Startup
Manager only edits the list.
</details>

<details>
<summary><b>Will my commands still run if I uninstall the app?</b></summary>

Yes. Each command is a normal autostart entry that runs a small bash script in your home folder. It
doesn't need Startup Manager at all. Turn commands off in the app before uninstalling if you don't
want them anymore.
</details>

<details>
<summary><b>Why doesn't <code>sudo</code> work in my command?</b></summary>

Commands run as you, in the background, without a terminal — so there's nowhere to type a password.
For things that need root at boot, a systemd service is the right tool.
</details>

<details>
<summary><b>I turned off a system service and something stopped working.</b></summary>

Turn on **Show System Services** in the menu, flip its switch back on (or choose **Restore Default**)
and log out and in again. The change only ever affected your account. If you can't open the app,
delete the file with the same name from `~/.config/autostart`.
</details>

<details>
<summary><b>My command didn't do anything at login. How do I find out why?</b></summary>

Open the command's **⋮** menu → **View Output**. Everything the command printed is there, with the
time it started and its exit code. Often it just ran before the network or a drive was ready — try a
delay or **Wait for Network**.
</details>

<details>
<summary><b>Does turning something off affect other users?</b></summary>

No. Everything is saved in your own `~/.config/autostart`. Other accounts on the computer are
unaffected.
</details>

## Credits

Startup Manager is a collaboration between a human developer and an AI assistant.

| | |
|---|---|
| **[cyb3rl00m](https://github.com/cyb3rl00m)** — creator & maintainer | Came up with the idea and the goal, programmed it alongside Claude in VSCode: a cleaner that *explains* instead of just deleting. Decides what the app does and how it should look and feel, tests every version on real hardware, finds and reports what's broken or confusing, pushed for the safety audit, handles packaging, releases and the community, and keeps the project going. |
| **[Claude](https://claude.ai)** by Anthropic — AI pair programmer | Helped cyb3rl00m debug the code and performed safety checks, following cyb3rl00m's direction and feedback. |

Every version is tested by cyb3rl00m on his own Ubuntu PC before it is released. Being upfront about
how the app is made matters to us — if you have questions about the code, open an issue.

## Contributing

Bug reports, ideas and pull requests are very welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).
Tried it on a distribution or desktop that isn't listed above? [Tell us](../../issues/new?template=bug_report.yml)
how it went. Found a security problem? Please see [SECURITY.md](SECURITY.md).

## More apps by cyb3rl00m

- [**Safe Disk Cleaner**](https://github.com/cyb3rl00m/safe-disk-cleaner) — see where your disk space
  went and what is safe to delete
- [**Crash Inspector**](https://github.com/cyb3rl00m/crash-inspector) — every crash and error on your
  system in one window
- [**Uninstaller**](https://github.com/cyb3rl00m/uninstaller) — completely remove APT, Snap and Flatpak
  apps

## License

[MIT](LICENSE) © 2026 cyb3rl00m
