# wa send to a WhatsApp group

**Type:** Decision doc
**Date:** 2026-11-25
**Status:** B and C tested live and failed. Groups are preview only for now.

## Problem

`wa send` reaches one person. It opens `whatsapp://send?phone=<digits>&text=<text>`.
That URL takes a phone number only. A group has no number, so wa refused. The first use
is a note to a customer group ("AirShelf x Maison Mugen", `120363429758875785@g.us`).

## What we know (checked 2026-11-25)

- WhatsApp for Mac 26.47.15 registers `whatsapp`, `whatsapp-consumer`, `upi` and one
  Facebook scheme. No documented URL opens a chat by JID. `abid` never worked.
- The strings in its binary show no `jid=` or `group` URL route. Swift keeps short
  strings inline, so this proves nothing either way.
- wa-launch holds Accessibility, and runs only the root-owned copy of wa. So every live
  probe of WhatsApp's window needs a new install on air, and that needs Eugene's sudo.
- Live probes on air ran from Terminal, which holds Accessibility, with Eugene's OK. They
  used only the self chat and the group that was already open. Nothing was sent.

## Criteria (fixed before ranking)

1. Wrong-target risk. Can the text land in another chat?
2. Proof. Can wa check the chat before it presses anything, and read the message back?
3. Unknowns. How many guesses about WhatsApp's window does it need?
4. Side effects. What does it touch besides the one chat?
5. Upkeep. How often does a WhatsApp update break it?

## Options

A. **`whatsapp://send?text=` with no phone, then pick the group in WhatsApp's chooser.**
   WhatsApp fills the composer itself, as for a person.
   - Strongest counterargument: nobody has seen this chooser on the Mac app. It may not
     exist, or it may send on its own "Send" button with no composer to check.
   - Failure mode: the chooser sends at once, so wa cannot check the chat first.
B. **Search the chat list for the exact name, open the result, check the header, paste
   the text, then send as for a person.** wa pastes through the clipboard and puts the
   old clipboard text back.
   - Strongest counterargument: it borrows the clipboard for a second. Anything copied
     in that second is lost. An image on the clipboard comes back as nothing.
   - Failure mode: the search result opens a different chat. The header check stops it.
C. **Search and open as in B, then set the composer's text through Accessibility.**
   - Strongest counterargument: Catalyst text views often ignore a set value. The
     composer looks full while WhatsApp's model is empty, so Return sends nothing.
   - Failure mode: an empty or stale send. Read-back catches it, after the press.
D. **A group invite link (`whatsapp://chat?code=`).** The database holds no invite
   code, and only admins can make one. Ruled out.

| | Wrong target | Proof | Unknowns | Side effects | Upkeep |
|---|---|---|---|---|---|
| A | low | weak if the chooser sends | the chooser itself | none | unknown |
| B | low, header checked | header + composer + read-back | search field, header | clipboard for ~1 s | search field label |
| C | low, header checked | header + read-back only | search field, header, set value | none | set value may break |

Facts that would change the ranking: a URL that opens a chat by JID (then use it, as for
a person). A chooser that leaves the text in a composer (then A needs no clipboard).
A composer that honours a set value (then C, with no clipboard).

## Recommendation

B. It is the only option where wa sees the right chat and the exact text before it
presses anything. The clipboard cost is small, and wa restores the text it held.

## Live probes (2026-11-25, WhatsApp 26.47.15, macOS 15.8.1)

Worked:
- Each chat-list row is an `AXButton`. Its `AXDescription` is the chat's exact name.
  AXPress on it opens the chat and focuses the composer.
- The open chat's header is the `NavigationBar_HeaderViewButton`. Its `AXDescription` is
  the chat name and its `AXValue` lists members. The composer is
  `ChatBar_ComposerTextView`. Labels carry U+200E marks, so strip them before comparing.
- Return, Delete and Cmd+A posted to WhatsApp's process act on the composer. Delete and
  Cmd+A only worked with WhatsApp in front.
- `whatsapp://send?text=` with no phone opens a "Send to" sheet. It has checkbox rows
  (`ForwardPicker_*_Cell_N`, described as "name, members"), a search field and Cancel.

Failed, with nothing put in the composer:
- Setting `AXValue` on the composer. It reads back, but WhatsApp's own state ignores it.
  Clearing it this way left the Send button showing, so Return would send the old text.
  That rules out C.
- `AXSelectedText`, and characters posted with `CGEventKeyboardSetUnicodeString`.
- Cmd+V posted to the process, in the background and in front. A system-wide Cmd+V with
  WhatsApp in front. The Edit > Paste menu item pressed through Accessibility. The
  clipboard held text in every case, and Paste was enabled. That rules out B.
- The chat list's search field is an `AXStaticText` and does not take focus.
- In the "Send to" sheet, neither AXPress nor a system-wide mouse click ticks a row. So
  A cannot pick the group either.
- Terminal passed `CGPreflightPostEventAccess`, so these failures are not a missing grant.

## Outcome — 2026-11-25

None of A, B or C works on WhatsApp 26.47. `wa send` previews a group message, with the
group name and member count, and refuses `--yes` and `--check` with exit 2. A person
still sends as before.

Facts that would reopen this: a WhatsApp update that takes pasted or typed text in the
composer, a URL that opens a chat by JID, or WhatsApp's Shortcuts "Send Message" action
accepting a group. That last one is untested and needs a shortcut built by hand.

## Questions for Eugene

1. (Unknowns) Should wa try WhatsApp's Shortcuts "Send Message" action for groups? It
   needs you to build one shortcut in the Shortcuts app once. Default: no, until a group
   send is needed again.

## Review notes (2026-11-25, automated security review)

- The title check could match a message that reads like the group name. Fixed: it now
  skips lists and scroll areas, where messages live.
- The unique-name check counted only visible chats. Fixed: it counts hidden chats and
  push names too. Address-book contacts are not in this database. A contact named like
  the group would show up in search, so read-back (exit 5) is the only check there.
- Clipboard exposure is moot. The clipboard path was removed after the probes.
- The opener, title check and clipboard code were then removed, because the live probes
  showed the text step cannot work. The member count, the unique-name check, and the
  read-back that demands the exact group JID stay.
