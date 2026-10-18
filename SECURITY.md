# Security policy

Startup Manager runs without root and only changes files in your own home folder. Still, it decides
what runs every time you log in, so bugs in that area are taken seriously.

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Instead use GitHub's private reporting:
go to the **Security** tab of this repository → **Report a vulnerability**.

Include what you did, what happened, and the version (`startup-manager --version`).
You will get an answer as soon as possible, and credit in the release notes if you like.

## What counts as a security issue

- The app writing, changing or deleting files outside `~/.config/autostart`,
  `~/.local/share/startup-manager` and `~/.local/state/startup-manager`
- A command script or log being readable or writable by other users
- A way for a crafted `.desktop` file (for example one shipped by another app) to make Startup Manager
  run something without you pressing **Run Now**

## Supported versions

Only the latest release receives fixes.
