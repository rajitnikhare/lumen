# Using Lumen day to day

This guide describes the **current interface**. For first-time installation, follow [Run locally](../README.md#run-locally) first. The native Mac app is optional; the same main workflows are available in the local browser interface.

## Open and unlock

If the Mac app is installed, open Lumen from Applications, click its menu-bar icon, or press **Control + Option + Space**. Enter your vault passphrase. For a new vault, choose at least 12 characters and keep the passphrase safe: there is no recovery or passphrase-change feature.

Closing the chat window hides it; it does not quit or immediately lock Lumen. Use **Lock** when you want to secure the workspace, or **Quit Lumen** from the menu to stop the app. It also locks after 30 minutes without an action. The device must be awake and logged in.

## Choose what you want to do

Chat opens first. Choose an action above the message box, enter the required information, and click its button:

| Action | How to use it |
|---|---|
| **Ask / suggest** | Ask a question, such as “What is the deadline in my project guide?” A local AI model is required. |
| **Save a note** | Type a thought and click **Save note**. Leave the memory checkbox off to store it without letting AI use it. No model is required. |
| **Remind me** | Type the task, select an exact local date/time, and click **Save reminder**. Reminders appear inside Lumen; they do not produce OS notifications. No model is required. |
| **Draft an email** | Describe the message, click **Create draft**, then review/edit and explicitly save the draft. Lumen cannot send email. |

Typing “save this” or “remind me” in **Ask / suggest** does not execute that action. Use the corresponding visible control. This is intentional: the model cannot silently change your records.

## Ask about a document

1. Select **Saved**, then the **Documents** tab, from the Mac window's view selector or the browser sidebar.
2. Click **+ Add document**, choose a PDF, DOCX, TXT, or Markdown file, and import it. Scanned PDFs need OCR first.
3. Enable **Allow local AI to summarize and retrieve this file**, either during import or afterward using **Authorize AI access**.
4. Return to chat and ask your question. Inspect source links before relying on important facts.

For a full-document summary, open the document's **Summarize / refocus** action instead of asking ordinary file Q&A. Chat uses selected excerpts, so it may miss information elsewhere in a long file.

You can also use **Attach file** in chat. Before asking, review the selected filename and consent to AI access and an encrypted copy of its extracted text. This is not a full document-content preview. After import, inspect the extracted text in **Saved > Documents**.

**Removing an attachment does not delete the saved document or revoke its AI permission.** Use **Saved > Documents** to revoke access or approve deletion of the saved copy.

## Share text or speak

Use **Share text** to paste text, or explicitly choose **Clipboard text** to read your clipboard. Review the shared text before submitting. Sharing alone does not call the model.

After an Ask response, shared context can remain attached in the collapsed review area. Choose **Clear shared context** when you do not want it reused. Successful note/reminder saves and inline draft saving clear shared text automatically.

In the Mac app, choose **Speak to Lumen**, or hold **`.` and press Enter while Lumen is focused**. Stop and review the transcript before clicking an action button. Dictation never submits the message automatically. The browser interface has no microphone option.

## Find and edit saved items

Use the view selector in the compact Mac window, or the browser sidebar:

- **Saved:** one page with four search-filterable tabs — **Documents** (inspect extracted text, summarize, revoke access, or delete), **Notes & memory** (edit notes/preferences and control AI access), **Email drafts** (edit or explicitly copy reviewed draft text), and **Mail** (inspect imported messages, revoke access, or delete). Each tab's Add/New form is hidden until you click its button.
- **Reminders:** view due items, mark complete, edit, or reopen. Suggestions from imported mail appear above your own reminders in a **Suggested from your email** section until you accept, edit, or discard them.
- **My day:** view counts, upcoming reminders, and recent items.

Only the selected item is deleted after you review and approve its deletion. Other copies in notes, conversations, or backups are not removed automatically. Discarding a suggested reminder (as opposed to a saved record) does not need this review step, since nothing was saved yet.

## If local AI is unavailable

You can still save notes and reminders. For AI features:

1. Start Ollama. The Mac app offers **Open Ollama**.
2. Ensure you have deliberately installed a local chat model.
3. Use **Set up local AI**, or open Settings, refresh models, select one, and save.

Lumen does not download a model or silently replace a saved model that has become unavailable. Optional semantic document search and internet research are not prerequisites for ordinary note-taking.

Saving Settings only contacts Ollama when you actually change the chat or embedding model. Removing or changing the saved Brave key succeeds even if Ollama is stopped.

## Optional mail import (read-only)

Lumen can read a Gmail inbox to suggest reminders for deadlines and appointments it finds. This is off by default.

1. Open **Settings & privacy > Optional mail import**. Enter your Gmail address and a Google **app password** — not your regular account password. [Create one here](https://support.google.com/accounts/answer/185833). Saving tests the connection immediately.
2. Go to **Saved > Mail** and click **Check for new mail**. This is the only trigger: nothing imports automatically or in the background, and nothing is ever sent from this account.
3. Imported messages (up to 200 per check, from the last 90 days) appear in the Mail tab, same as Documents — inspect, revoke AI access, or delete them.
4. If Lumen finds an explicit date in a new message, it appears in **Reminders > Suggested from your email**. **Accept** saves it as-is; **Edit before accepting** lets you fix the title/date/details first; **Discard** removes the suggestion. Always check the suggested date against the actual message — this is a best-effort suggestion, not a verified extraction.

Authorized mail also becomes searchable in chat, the same way documents and notes are: you can ask things like "when does my flight leave" and get a cited answer. Revoking a message's AI access removes it from future answers.

## Optional research and evaluation

**Research** requires a Brave key and approval of the exact public query. Do not include private details. Lumen compares returned snippets, not full articles, and does not search automatically from chat.

Developer evaluations and the optional LangSmith export are **not required to use Lumen**. They are separate command-line tools for bundled synthetic data, not a feature that traces your daily chats. See the [evaluation guide](evaluation/README.md) only if you are testing or developing the project.
