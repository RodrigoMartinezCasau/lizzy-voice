Public showcase of a private codebase in development since August 2026.

# Lizzy

Lizzy is the voice assistant for the Fiodos team. You say "hey lizzy", it listens, answers out loud, and waits a few seconds for a follow-up.

This repository is the voice loop only. Home-device integrations and developer-tool commands stay in the private repository.

## 📊 The real codebase

The private repository has 2 commits, both on 30 August 2026.

Lines of tracked source:

| Language | Lines |
|---|---:|
| Python | 3,241 |
| Swift | 115 |

```text
.
├── jarvis/
│   ├── audio/
│   ├── brain/
│   ├── commands/
│   ├── lights/
│   ├── tools/
│   └── wake/
├── assets/
└── scripts/
```

```mermaid
flowchart LR
  Mic["Microphone"] --> Wake["Wake word"]
  Wake --> Speech["Speech to text"]
  Speech --> Brain["Reply"]
  Brain --> Voice["Text to speech"]
  Voice --> Speaker["Speaker"]
```
