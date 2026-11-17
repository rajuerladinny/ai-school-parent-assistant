---
title: Sunrise Valley Parent Assistant
emoji: 🎓
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: RAG assistant that answers only from approved school docs
---

# Sunrise Valley Parent Assistant: live demo

A self-hosted AI assistant that answers parents' questions **only from documents a school has approved**, shows the source for every answer, and hands anything it can't answer to school staff.

**Everything here is fictional.** Sunrise Valley School does not exist. The staff portal is read-only, and nothing you type is stored.

## Try it
- Ask: *Is the school nut-free?*, *When do after-school clubs run?* or *Is there a sibling discount on fees?*
- Ask something the school hasn't documented, like *Can my son bring his pet rabbit to show and tell?*, and see it handed to staff instead of guessed.
- Click **Sign in as demo parent** to see policy updates and staff replies.
- Open the **Staff portal** with the demo key shown on screen to see the question inbox, knowledge base, policies and conflict checks.

## How it works
Python + FastAPI, local semantic search with ChromaDB and Sentence Transformers (`all-MiniLM-L6-v2`), SQLite. No paid AI API.

Source code, architecture and setup: https://github.com/rajuerladinny/ai-school-parent-assistant
