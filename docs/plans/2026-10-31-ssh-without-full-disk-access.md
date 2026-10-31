# Reading WhatsApp over SSH without giving sshd Full Disk Access

**Type:** Decision doc
**Date:** 2026-10-31
**Status:** decided, D with the existing key

## Problem

`wa` reads the Mac over SSH. macOS only lets it in when `/usr/libexec/sshd-keygen-wrapper`
has Full Disk Access. That grant covers every SSH login, with any key, running any
command. Such a login can read Mail, Messages, Safari history, Desktop, Documents and every
other app's data. The machine that SSHes in runs agents that read untrusted text,
including WhatsApp messages. (Eugene, 2026-10-31: "full disk access is actually quite bad
for ssh".)

## How macOS decides

- TCC checks the "responsible process" and passes grants down to child processes.
- A process started over SSH has `sshd-keygen-wrapper` as its responsible process. So a
  Full Disk Access grant on any other binary does nothing when that binary is started
  over SSH.
- A job started by launchd is its own responsible process. A grant on that job's own
  binary works. Backup tools run from launchd rely on this. For a script, the grant must
  go on the interpreter (`/bin/bash`, `python3`). That gives every script run by that
  interpreter Full Disk Access, so it is no better.
- A signed launcher can use a private macOS call to give up its parent's responsibility
  and own its grant even when started from SSH. `tcc-venv` does this. It is undocumented
  and may break on a macOS update.
  Sources: <https://pypi.org/project/tcc-venv/>,
  <https://developer.apple.com/forums/thread/661178>,
  <https://www.qt.io/blog/the-curious-case-of-the-responsible-process>

Whatever holds the grant must do one fixed job, and its code must be owned by root. If you
can edit what it runs, so can anything running as you. Then you have given Full Disk
Access to your whole account again.

## Criteria (fixed before ranking)

1. Exposure. What an SSH login, or a stolen key on the other machine, can read on the Mac.
2. Freshness. Live data or minutes old.
3. Copies at rest. Does it make a new unprotected copy of the chats?
4. Fragility. Will a macOS or WhatsApp update break it, and does it fail loudly?
5. Effort. Build cost and upkeep.

## Options

| | 1 Exposure | 2 Freshness | 3 Copies | 4 Fragility | 5 Effort |
|---|---|---|---|---|---|
| A. Keep Full Disk Access on sshd | every SSH login reads all app data | live | none | stable | none |
| B. Snapshot job | SSH sees one WhatsApp copy | up to ~1 min old | full copy outside the protected folder | stable | small |
| C. Launchd socket job | SSH reads WhatsApp through wa only, no other app data | live | none | stable | most |
| D. Signed launcher | same as C | live | none | private API, fails closed | medium |

**A. Keep it.** Zero work.
Strongest objection: a stolen key or a prompt-injected agent on the other machine reads
everything on the Mac.
Failure mode: nothing breaks, so nobody notices the exposure.

**B. Snapshot job.** A launchd job runs a small signed binary that holds the grant. On each
change it copies the database with `VACUUM INTO` to `~/.wa/mirror`. `wa` reads that copy
through `WA_DB`. Remove the grant from sshd.
Strongest objection: the copy sits outside WhatsApp's protected folder, so every program
you run can read it without asking. Media needs copying too, and its size is unknown.
Failure mode: the job stops after an update and `wa` serves old data quietly. It needs an
age check in `wa status`.

**C. Locked key and a launchd socket job.** Add a second SSH key used only by `wa`. Its
`authorized_keys` line forces one command and turns off forwarding. That command passes the
request to a launchd socket job. The job holds the grant and runs a root-owned copy of `wa`
with allowlisted arguments. Remove the grant from sshd.
Strongest objection: the most moving parts for one personal tool. Every `wa` update needs a
`sudo` reinstall, and the socket needs its own way to return exit codes.
Failure mode: a broken job makes `wa` exit 3, which is loud.

**D. Locked key and a signed launcher.** Same locked key. The forced command is a small
signed C launcher. It gives up sshd's responsibility, owns the grant, and runs the
root-owned `wa` with allowlisted arguments. Exit codes pass through. Remove the grant from
sshd.
Strongest objection: it relies on an undocumented macOS call.
Failure mode: a macOS update breaks the call and `wa` exits 3. It fails closed, never open.

## Facts that would change the ranking

- Whether a terminal app on the Mac has Full Disk Access. If one does, an SSH login can put
  code in `~/.zshrc`, and it gains Full Disk Access when you next open a terminal. Removing
  the grant from sshd then only adds a delay. The locked key in C and D matters more.
- Whether the other machine's main SSH key into the Mac stays a full shell. If it does, a
  compromised machine can still run any code on the Mac as you. Removing the grant then
  protects only TCC folders. That is a separate decision.
- WhatsApp media size, which drives the cost of B.
- Checked 2026-10-31, after Eugene removed the sshd grant: `wa` over SSH exits 3 as
  expected. No terminal app has Full Disk Access. One other app does, and its scripts were
  synced from the other machine through a shared folder. So the other machine could plant
  code that runs with full access the next time Eugene used that app, with no SSH at all.
  That was wider than sshd ever was, and D does not close it. Fixed the same day by moving
  that app's settings to a local folder.

## Recommendation

D. It is live, keeps no copy, and needs the least code of the safe options. It fails
closed. C is the fallback if a private API is not acceptable.

## How D works

Eugene, 2026-10-31: "can we just use the old key?" Yes. The main key stays a full shell
(question 2), so anyone holding it could call `wa-launch` anyway. A separate locked key
adds nothing until the main key is limited too. So D uses the existing key, and
`wa-launch` alone is the gate. The same holds for C.

1. `wa` runs `ssh <mac> /usr/local/libexec/wa/wa-launch <args>` with the existing key.
2. Anything running as the user can call `wa-launch`, so it must check its own arguments.
3. `wa-launch` is about 60 lines of C. It is root-owned, signed with hardened runtime, and
   is the only binary with Full Disk Access. sshd loses its grant.
4. `wa-launch` checks its arguments against an allowlist: `chats`, `read`, `search`,
   `recent`, `media --b64`, `status`.
5. It starts a copy of itself through the private "disclaim" spawn call. That copy is its
   own responsible process. The copy runs `/usr/bin/python3 -I /usr/local/libexec/wa/wa`
   with a cleared environment. Python inherits the copy's responsibility, so TCC checks
   `wa-launch`'s grant.
6. Output and the exit code pass back through the copy, the first `wa-launch` and SSH.

Root owns both files, so nothing running as the user can change what the granted binary
runs. Running the same `wa` without `wa-launch` gets no grant. A `wa` update needs a `sudo`
install. A changed `wa-launch` changes its signature and needs a new grant by hand.

## Questions for Eugene

1. (Criteria 1, 4) Which option should we build: D, C, B, or keep A?
   Eugene, 2026-10-31: D, with the existing key, then "continue".
2. (Criterion 1) Should the other machine's main SSH key into the Mac also be limited?
   That is a separate change.
   Eugene, 2026-10-31: not now.

## Decision — 2026-10-31

Build D with the existing SSH key. `wa-launch` is the only binary with Full Disk Access.
sshd lost its grant the same day, and the synced app settings moved to a local folder.

Two details changed while building:

- `wa-launch` does not parse `wa` arguments. Its walls are a fixed root-owned script, a
  check that the script and every folder above it are owned by root and writable only by
  root, a cleared environment, and a refusal of `-o`. `-o` would let the granted process
  write into folders macOS protects.
- It re-executes itself with responsibility disclaimed (`POSIX_SPAWN_SETEXEC`, as
  `dotnet/macios` does), so it stays one process before it starts Python.
