#!/bin/sh
# Build wa-launch and install it, with a copy of wa, into /usr/local/libexec/wa, owned by
# root. Run it on the Mac from a checkout of the repo. It asks for your password once.
# Run it again after updating wa, so the copy the launcher runs matches.
set -eu

DEST=/usr/local/libexec/wa
ID=dev.evoleinik.wa-launch
[ "$(uname)" = Darwin ] || { echo "install.sh: run this on the Mac" >&2; exit 2; }
cd "$(dirname "$0")/.."

# Pin the Command Line Tools Python. The /usr/bin/python3 stub follows xcode-select and
# could land in an Xcode the user owns, whose files anything running as you could edit.
PY=/Library/Developer/CommandLineTools/usr/bin/python3
[ -x "$PY" ] || { echo "install.sh: needs the Command Line Tools: xcode-select --install" >&2; exit 3; }
PYBIN=$("$PY" -I -S -c 'import os, sys; print(os.path.realpath(sys.executable))')
PYLIB=$("$PY" -I -S -c 'import sysconfig; print(sysconfig.get_paths()["stdlib"])')
bad=$(find "$PYBIN" "$PYLIB" ! -type l \( ! -user root -o -perm -0020 -o -perm -0002 \) | head -3)
[ -z "$bad" ] || { echo "install.sh: Python files not owned and writable only by root:" >&2; echo "$bad" >&2; exit 3; }

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cc -O2 -Wall -Wextra -Werror -DWA_PYTHON="\"$PYBIN\"" -DWA_PYLIB="\"$PYLIB\"" \
  -o "$tmp/wa-launch" launcher/wa-launch.c
codesign --force --sign - --options runtime --identifier "$ID" "$tmp/wa-launch"
cdhash() { codesign -dvvv "$1" 2>&1 | sed -n 's/^CDHash=//p'; }
old=$( [ -e "$DEST/wa-launch" ] && cdhash "$DEST/wa-launch" || true)
new=$(cdhash "$tmp/wa-launch")

sudo install -d -o root -g wheel -m 755 /usr/local/libexec "$DEST"
sudo install -o root -g wheel -m 755 "$tmp/wa-launch" "$DEST/wa-launch"
sudo install -o root -g wheel -m 644 bin/wa "$DEST/wa"
echo "installed $DEST/wa-launch and $DEST/wa ($("$DEST/wa-launch" --version))"

if [ "$old" != "$new" ]; then
  cat <<EOF
Next, grant Full Disk Access to the launcher, once:
  System Settings > Privacy & Security > Full Disk Access > +
  press Cmd+Shift+G, paste $DEST/wa-launch, press Open, then turn it on.
Remove /usr/libexec/sshd-keygen-wrapper from that list if it is there.
EOF
else
  echo "the launcher did not change, so its Full Disk Access grant still applies"
fi
