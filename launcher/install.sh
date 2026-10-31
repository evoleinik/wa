#!/bin/sh
# Build wa-launch and install it, with a copy of wa, into /usr/local/libexec/wa, owned by
# root. Run it on the Mac from a checkout of the repo. It asks for your password once.
# Run it again after updating wa, so the copy the launcher runs matches.
set -eu

DEST=/usr/local/libexec/wa
ID=dev.evoleinik.wa-launch
[ "$(uname)" = Darwin ] || { echo "install.sh: run this on the Mac" >&2; exit 2; }
cd "$(dirname "$0")/.."

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cc -O2 -Wall -Wextra -Werror -o "$tmp/wa-launch" launcher/wa-launch.c
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
