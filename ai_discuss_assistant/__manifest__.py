# -*- coding: utf-8 -*-
{
    'name': 'AI Discuss Assistant & Smart Agent',
    'version': '18.0.1.0.0',
    'category': 'Productivity/Discuss',
    'summary': 'AI Chatbot in Discuss with Odoo Context, Safe ORM Actions, and PostgreSQL Read-Only Querying',
    'description': """
AI Discuss Assistant for Odoo 18
================================
Transform Odoo Discuss into a powerful AI Assistant directly connected to your ERP.

Key Features:
-------------
* **Native Discuss Integration**: Direct chat with AI Assistant or @mention in group channels.
* **Context-Aware**: Injects active user details, company info, date, and Odoo environment context.
* **Smart Input via Safe ORM Actions**:
  - Create records (Contacts, Leads, Orders, Tasks) via Odoo ORM under user security context.
  - Generates direct clickable links to created records in Discuss chat.
* **PostgreSQL Analytical Queries**:
  - Safe, read-only SELECT query tool for statistical summaries and data exploration.
* **OpenAI-Compatible & BYOK**:
  - Works with any OpenAI-compatible API gateway (9router, LiteLLM, Ollama, OpenAI, Groq, etc.).
  - Reuses settings from document_extraction_base if installed.
* **Non-Blocking Asynchronous Execution**:
  - Zero UI freezing; uses daemon thread and Odoo real-time websocket/bus push.
    """,
    'author': 'Tyr',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/ai_discuss_assistant_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
