# wa send to a WhatsApp group

**Type:** Decision doc
**Date:** 2026-11-25
**Status:** recommendation, waiting on a live check on air

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
- The group's own window has a search field in the chat list, and the chat header
  shows the group name. Not yet checked through Accessibility.

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

## Questions for Eugene

1. (Side effects) Is it fine that wa borrows the clipboard for about a second during a
   group send? Default: yes, it puts back the text that was there.
   A clipboard manager on air would record the group name and the message text. pbcopy
   cannot mark them as transient.

## Review notes (2026-11-25, automated security review)

- The title check could match a message that reads like the group name. Fixed: it now
  skips lists and scroll areas, where messages live.
- The unique-name check counted only visible chats. Fixed: it counts hidden chats and
  push names too. Address-book contacts are not in this database. A contact named like
  the group would show up in search, so read-back (exit 5) is the only check there.
- Clipboard exposure is accepted for now, as question 1 asks.
