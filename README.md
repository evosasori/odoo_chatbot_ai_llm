# Odoo Chatbot AI LLM & ERP Copilot (Odoo 18)

An intelligent, context-aware AI Chatbot natively integrated into Odoo Discuss. Connects seamlessly with OpenAI-compatible gateways (9router, LiteLLM, Ollama, OpenAI, Groq) to guide users, run analytical PostgreSQL queries, execute safe ERP actions, and trigger record buttons via Odoo ORM.

---

## 🌟 Key Features

1. **Native Discuss Integration**:
   - Chat 1-on-1 with `AI Assistant` or invite and `@mention` the bot in group channels.
   - Built-in real-time typing indicator (`AI Assistant is typing...`) via Odoo WebSocket bus.
2. **Context-Aware ERP Copilot**:
   - Understands active user info, company details, currency, server date & time, and model definitions.
3. **Safe Record Creation & Compound Flows**:
   - Create contacts (`res.partner`), quotations (`sale.order`), leads, products, and tasks.
   - Compound multi-step actions (e.g. creating customer + product + quotation in one request).
   - Records are created in `draft` state with direct clickable Odoo URLs for review.
4. **Action & Button Execution (`execute_model_method`)**:
   - Trigger buttons directly from chat (e.g., confirm quotation, cancel order, validate picking).
5. **Analytical PostgreSQL Queries**:
   - Safe, read-only `SELECT` queries for statistics and aggregations.
6. **Strict 2-Layer Security Guardrails**:
   - Blocks module installation/uninstallation/upgrades (`ir.module.module`).
   - Blocks password modification, user deletion, or credential leaks (`res.users`, passwords, API keys).
   - Blocks destructive SQL commands (`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`).
7. **Dynamic Model Fetcher**:
   - One-click sync button (`🔄 Ambil Model dari API`) to load available LLM models from your gateway directly into a dropdown list.

---

## 📦 Directory Structure

```
odoo_chatbot_ai_llm/
└── ai_discuss_assistant/
    ├── __init__.py
    ├── __manifest__.py
    ├── data/
    │   └── ai_discuss_assistant_data.xml
    ├── models/
    │   ├── __init__.py
    │   ├── ai_discuss_model.py
    │   ├── res_config_settings.py
    │   ├── ai_agent_service.py
    │   └── discuss_channel.py
    ├── security/
    │   └── ir.model.access.csv
    └── views/
        └── res_config_settings_views.xml
```

---

## 🚀 Installation & Setup

1. Clone or copy this repository into your Odoo `addons_path`.
2. Update App List in Odoo Developer Mode.
3. Install the module **AI Discuss Assistant & Smart Agent** (`ai_discuss_assistant`).
4. Go to **Settings > General Settings > AI Discuss Assistant**:
   - Enter your **AI Assistant Base URL** (e.g., `https://9router.triadiputra.my.id/v1`).
   - Enter your **AI Assistant API Key**.
   - Click **🔄 Ambil Model dari API** to populate models.
   - Select your model and test with **⚡ Test AI Assistant Connection**.
5. Open Odoo Discuss, start a chat with **AI Assistant**, and enjoy!

---

## 📄 License
LGPL-3
