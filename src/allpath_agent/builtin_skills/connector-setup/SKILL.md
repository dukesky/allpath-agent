---
name: connector-setup
description: Guide and diagnose Telegram, Slack, or WhatsApp setup without exposing secrets.
---

# Connector Setup

1. Confirm that a live reasoning model is connected.
2. Ask which connector the user wants, unless it is already clear.
3. Use Allpath's conversational connector workflow rather than inventing setup steps.
4. Keep tokens in hidden inputs and never ask the user to paste credentials into normal chat.
5. Treat deterministic connector verification as the only proof of success.
6. If setup fails, explain the exact failed layer: credentials, provider verification, gateway runtime, webhook, or delivery.
