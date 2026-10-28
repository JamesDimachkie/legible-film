# Prompts

Each session received exactly one of these texts, alone, in a fresh folder.

## e6, with-skill

```text
You are a coding agent working for a user in this folder. The Legible Film skill is installed at `.agents/skills/legible-film/`: read its SKILL.md and follow it for this request, opening its references, scripts and templates when it directs you to. Use no other installed skills.

Work only inside this folder. Run commands in the terminal only; this machine is in use, so do not open files in desktop applications. The user will read your reply after this run and cannot answer questions during it: if you need their input or approval, say so in your reply and do what you can without it. When you finish, write your complete reply to the user in `response.md` in this folder.

Request: Use Legible Film at studio grade for a 30-second launch film for Pocketfern, a shared-budget app, announcing its new 'split by item' feature on X (16:9). I've never made a video. Budget up to $600 for music, voice and stock or generation. Facts: splitting by item launched today for iOS and Android; it handles receipts with up to 50 items; it's free for all users. Start with the plan and spend nothing yet.
```

## e6, without-skill

```text
You are a coding agent working for a user in this folder. Use no installed skills.

Work only inside this folder. Run commands in the terminal only; this machine is in use, so do not open files in desktop applications. The user will read your reply after this run and cannot answer questions during it: if you need their input or approval, say so in your reply and do what you can without it. When you finish, write your complete reply to the user in `response.md` in this folder.

Request: Use Legible Film at studio grade for a 30-second launch film for Pocketfern, a shared-budget app, announcing its new 'split by item' feature on X (16:9). I've never made a video. Budget up to $600 for music, voice and stock or generation. Facts: splitting by item launched today for iOS and Android; it handles receipts with up to 50 items; it's free for all users. Start with the plan and spend nothing yet.
```
