# Messengers

## 1.0.2

- **Posts and polls are off by default.** They are meant for members and a
  messenger group may be open to anyone; a club switches them on in the
  settings. Clubs that already saved their settings keep what they chose.
- One test message per messenger a minute (429 otherwise); the test message
  no longer names who sent it (the audit log does).
- Security: calls go to the address that passed the public-address check
  (no DNS rebinding), a token with a space or line break gives a plain
  error instead of a server error with the token in the log, and retrying
  a failed message is audited.
- The menu entry moves to the new sidebar area **Kommunikation**, next to Mail,
  Letters and Inbox. Needs a Hubra with that area (after 0.2.5); older
  versions show it under a heading of its own.

## 1.0.1

The Einstellungen button on the Messengers page opens the plugin's own
settings form, not the whole module list. Needs Hubra with
`/app/settings/modules?module=<code>` (newer than 0.2.4); older versions show
the module list as before.

## 1.0.0

First version: new events, posts, polls and reminders in Telegram (bot),
Signal (signal-cli REST API) and Matrix (client API); only what the whole
club may see; three tries per message; a page with the sent messages, test
messages and retries.
