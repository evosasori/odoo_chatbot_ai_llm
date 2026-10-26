# -*- coding: utf-8 -*-
import json
import re
import requests
import logging
from markupsafe import Markup
from odoo import api, fields, models
from odoo.tools import html2plaintext
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)

FORBIDDEN_SQL_KEYWORDS = re.compile(
    r'\b(insert|update|delete|drop|alter|truncate|create|grant|revoke|execute|copy|vacuum|into)\b',
    re.IGNORECASE
)
SENSITIVE_SQL_COLUMNS = re.compile(
    r'\b(password|password_crypt|totp_secret|api_key|secret)\b',
    re.IGNORECASE
)

# Models completely blocked from AI creation / write operations
RESTRICTED_MODELS_WRITE = {
    # 1. Module & Core System Lifecycle
    'ir.module.module',
    'ir.module.module.dependency',
    'ir.model',
    'ir.model.fields',
    'ir.model.data',
    'ir.cron',
    'ir.config_parameter',
    # 2. User Identity, Credentials & Security Access Control
    'res.users',
    'res.groups',
    'ir.model.access',
    'ir.rule',
    'res.users.apikeys',
    'auth_totp.wizard',
    'change.password.wizard',
    'change.password.user',
    # 3. Server Actions & Views
    'ir.actions.server',
    'ir.actions.act_window',
    'ir.ui.view',
}

# Forbidden action button methods (dangerous lifecycle & security methods)
RESTRICTED_METHODS = {
    # Module Lifecycle Methods
    'button_immediate_install',
    'button_immediate_upgrade',
    'button_immediate_uninstall',
    'button_install',
    'button_upgrade',
    'button_uninstall',
    'update_list',
    'apply_scheduled_upgrades',
    # User / Auth / Password Methods
    'action_reset_password',
    'action_change_password',
    'preference_change_password',
    'action_archive',
    # Cron & Background jobs
    'method_direct_trigger',
    # Generic destructive ORM methods
    'unlink',
    'read',
    'write',
    'create',
    'search',
    'fields_get',
    'copy',
}

# Prohibited sensitive fields on ANY model
RESTRICTED_FIELDS = {
    'password',
    'password_crypt',
    'new_password',
    'totp_secret',
    'api_key',
    'groups_id',
}


class AiAgentService(models.AbstractModel):
    _name = 'ai.agent.service'
    _description = 'AI Assistant Agent Service'

    @api.model
    def get_ai_config(self, company=None):
        """Retrieve active AI endpoint, credentials, and tuning parameters."""
        ICP = self.env['ir.config_parameter'].sudo()
        company = company or self.env.company

        endpoint = (
            ICP.get_param('ai_discuss.endpoint') or
            getattr(company, 'custom_ai_endpoint', '') or
            'https://api.openai.com/v1'
        ).rstrip('/')

        api_key = (
            ICP.get_param('ai_discuss.api_key') or
            getattr(company, 'custom_ai_api_key', '') or
            ''
        )

        model = (
            ICP.get_param('ai_discuss.model') or
            getattr(company, 'custom_ai_model', '') or
            'gpt-4o-mini'
        )

        temperature = float(ICP.get_param('ai_discuss.temperature', 0.5))
        max_history = int(ICP.get_param('ai_discuss.max_history', 8))
        enable_tools = ICP.get_param('ai_discuss.enable_tools', 'True').lower() in ('true', '1')
        enable_sql = ICP.get_param('ai_discuss.enable_sql', 'True').lower() in ('true', '1')
        custom_prompt = ICP.get_param('ai_discuss.system_prompt', '')

        return {
            'endpoint': endpoint,
            'api_key': api_key,
            'model': model,
            'temperature': temperature,
            'max_history': max_history,
            'enable_tools': enable_tools,
            'enable_sql': enable_sql,
            'custom_prompt': custom_prompt,
        }

    @api.model
    def build_system_context(self, user, company):
        """Construct a detailed ERP context prompt for the AI agent."""
        currency_name = company.currency_id.name if company.currency_id else 'IDR'
        today_str = fields.Date.today().strftime('%Y-%m-%d')
        now_str = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')

        config = self.get_ai_config(company)
        custom_instructions = config.get('custom_prompt', '').strip()

        context_prompt = f"""You are AI Assistant, an expert ERP copilot built natively inside Odoo 18.
You are chatting with an internal ERP user through Odoo Discuss.

### Current Session Context:
- Active User: {user.name} (Login: {user.login}, User ID: {user.id})
- Active Company: {company.name} (Company ID: {company.id})
- Currency: {currency_name}
- Current Date: {today_str}
- Current Server Time: {now_str}
- ERP Version: Odoo 18.0 Community/Enterprise

### Capabilities & Operating Rules:
1. **Help & Guide**: Answer user questions regarding business operations, master data, navigation, and Odoo usage.
2. **Safe Input & Record Creation**:
   - If the user asks to create a record (e.g., Contact, Quotation/Sales Order, Lead, Task, Product), you MUST use the `create_record` tool.
   - For transactional records having a status/state (like sales orders, purchase orders, invoices, expenses), ALWAYS set `state='draft'` or allow default values. Never confirm or post financial transactions directly.
   - When you create a record, ALWAYS provide the user with the direct link returned by the tool so they can immediately review and confirm it in Odoo.
3. **Execute Actions & Button Clicks**:
   - When the user asks to click a button, confirm, validate, or execute an action on a record (e.g., "tekan tombol confirm pada SO S00026", "approve pengajuan", "jalankan aksi"), use the `execute_model_method` tool with `model`, `record_id`, and `method_name`.
   - If you do not know the record ID yet, search for the record first using `search_read_records`.
4. **Compound Operations (Chained Creation)**:
   - When the user asks to create a document requiring multiple records (e.g., Sales Order with a new partner and new product), perform all required creations efficiently.
   - For `sale.order`, use `order_line: [[0, 0, {{"product_id": <id>, "product_uom_qty": <qty>, "name": <name>}}]]`.
   - Complete all dependent records and return links to each newly created record.
5. **Data Inspection & Exploration**:
   - To inspect fields of an Odoo model before creating or searching, use `get_model_fields`.
   - To find or filter existing records, use `search_read_records`. IMPORTANT: the domain `id` in Odoo is an integer record ID, while a document number like "REG5813" or "S00026" is the `name` field — always search `[("name", "=", "REG5813")]`, never `[("id", "=", 5813)]`.
   - For complex analytical questions, aggregations, or stats (e.g. "how many active customers do we have?"), you can use `query_database_readonly` to execute a fast SQL SELECT. PostgreSQL tip: `ir_model.name` is a translatable JSONB column — cast it with `name::text` before using ILIKE on it.
6. **Communication Style**:
   - Respond in the language used by the user (primarily Indonesian / English).
   - Format responses using clean HTML tags (`<p>`, `<b>`, `<ul>`, `<li>`, `<code>`, `<a href="...">`).
   - Be concise, direct, helpful, and professional.

### 🛑 Strict Security Boundaries & Prohibitions (DILARANG KERAS):
1. **Module & System Lifecycle**:
   - DILARANG KERAS meng-install, meng-upgrade, meng-uninstall, atau memanipulasi modul aplikasi (`ir.module.module`).
   - Jika pengguna meminta install/uninstall aplikasi atau modul, TOLAK SECARA SOPAN dan jelaskan bahwa instalasi/uninstal modul hanya boleh dilakukan langsung oleh Administrator sistem melalui antarmuka resmi Apps demi mencegah downtime dan kehilangan data permanen.
2. **User Identity, Password & Access Control**:
   - DILARANG membuat pengguna baru (`res.users`), mengubah/mereset password pengguna, atau melihat/mengubah kredensial dan token autentikasi.
   - DILARANG memodifikasi hak akses, grup pengguna (`res.groups`), atau aturan keamanan (`ir.model.access`, `ir.rule`).
3. **System Integrity**:
   - DILARANG mengubah konfigurasi parameter sistem (`ir.config_parameter`), jadwal otomatis cron (`ir.cron`), tampilan view (`ir.ui.view`), atau server actions.
4. **Respon Penolakan**:
   - Jika pengguna meminta salah satu dari tindakan terlarang di atas, berikan penjelasan penolakan yang ramah, sopan, dan profesional dalam Bahasa Indonesia tanpa memanggil tool create atau execute method.
"""
        if custom_instructions:
            context_prompt += f"\n### Custom Administrator Instructions:\n{custom_instructions}\n"

        return context_prompt

    @api.model
    def get_tool_definitions(self, enable_tools=True, enable_sql=True):
        """Returns OpenAI-compatible function calling tool schemas."""
        tools = []
        if not enable_tools:
            return tools

        tools.append({
            "type": "function",
            "function": {
                "name": "get_model_fields",
                "description": "Get field definitions and technical specifications for an Odoo model (e.g. 'res.partner', 'sale.order', 'crm.lead', 'product.product'). Use this to see field names before creating or querying records.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {
                            "type": "string",
                            "description": "Technical Odoo model name (e.g. 'res.partner', 'sale.order', 'crm.lead', 'project.task')"
                        }
                    },
                    "required": ["model"]
                }
            }
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "search_read_records",
                "description": "Search and retrieve records from an Odoo model using Odoo ORM domain filters under current user security context.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {
                            "type": "string",
                            "description": "Technical Odoo model name (e.g. 'res.partner', 'sale.order', 'product.template')"
                        },
                        "domain": {
                            "type": "array",
                            "description": "Odoo search domain, e.g. [['name', 'ilike', 'John'], ['customer_rank', '>', 0]]",
                            "items": {"type": "array"}
                        },
                        "fields": {
                            "type": "array",
                            "description": "List of field names to fetch (e.g. ['name', 'email', 'phone', 'state'])",
                            "items": {"type": "string"}
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of records to return (default 10, max 50)"
                        }
                    },
                    "required": ["model"]
                }
            }
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "create_record",
                "description": "Create a new record in an Odoo model via Odoo ORM. Runs under the active user's permissions and enforces all business constraints, sequences, and validations. Always set state='draft' for transactional models.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {
                            "type": "string",
                            "description": "Technical Odoo model name (e.g. 'res.partner', 'crm.lead', 'sale.order', 'project.task')"
                        },
                        "values": {
                            "type": "object",
                            "description": "Key-value dictionary of fields to write (e.g. {'name': 'PT Sinar Jaya', 'email': 'sales@sinarjaya.com', 'is_company': true})"
                        }
                    },
                    "required": ["model", "values"]
                }
            }
        })

        tools.append({
            "type": "function",
            "function": {
                "name": "execute_model_method",
                "description": "Click a button or execute an action method on a specific Odoo record (e.g. 'action_confirm', 'button_validate', 'action_cancel', 'action_done', or any custom action button method). Enforces user security rules.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "model": {
                            "type": "string",
                            "description": "Technical Odoo model name (e.g. 'sale.order', 'stock.picking', or custom model name)"
                        },
                        "record_id": {
                            "type": "integer",
                            "description": "The integer ID of the record on which to press the button / execute the method"
                        },
                        "method_name": {
                            "type": "string",
                            "description": "The Python method / button name to execute (e.g. 'action_confirm', 'button_validate', 'action_approve')"
                        }
                    },
                    "required": ["model", "record_id", "method_name"]
                }
            }
        })

        if enable_sql:
            tools.append({
                "type": "function",
                "function": {
                    "name": "query_database_readonly",
                    "description": "Execute a read-only PostgreSQL SELECT query to inspect database records, calculate statistical metrics, or explore tables. Only SELECT queries are allowed; write operations are strictly blocked.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "PostgreSQL SELECT statement (e.g. 'SELECT count(*) FROM res_partner WHERE active=true')"
                            }
                        },
                        "required": ["query"]
                    }
                }
            })

        return tools

    @api.model
    def execute_tool(self, user_id, tool_name, arguments_str):
        """Safely dispatches and executes a tool call under the user's Odoo security context."""
        try:
            args = json.loads(arguments_str) if isinstance(arguments_str, str) else (arguments_str or {})
        except Exception as e:
            return json.dumps({"error": f"Invalid JSON arguments: {str(e)}"})

        user_env = self.with_user(user_id).env

        # --- TOOL: GET MODEL FIELDS ---
        if tool_name == 'get_model_fields':
            model_name = args.get('model', '').strip()
            if model_name not in user_env:
                return json.dumps({"error": f"Model '{model_name}' does not exist in Odoo."})

            try:
                fields_dict = user_env[model_name].fields_get(
                    attributes=['string', 'type', 'required', 'readonly', 'relation']
                )
                # Filter down to essential fields to prevent context blowout
                summary = {}
                for f_name, f_info in list(fields_dict.items())[:60]:
                    summary[f_name] = {
                        "string": f_info.get("string"),
                        "type": f_info.get("type"),
                        "required": f_info.get("required", False),
                        "readonly": f_info.get("readonly", False),
                        "relation": f_info.get("relation") or None,
                    }
                return json.dumps({"model": model_name, "fields": summary})
            except Exception as e:
                return json.dumps({"error": str(e)})

        # --- TOOL: SEARCH READ RECORDS ---
        elif tool_name == 'search_read_records':
            model_name = args.get('model', '').strip()
            domain = args.get('domain') or []
            fields_to_read = args.get('fields') or ['name']
            limit = min(int(args.get('limit', 10)), 50)

            if model_name not in user_env:
                return json.dumps({"error": f"Model '{model_name}' does not exist in Odoo."})

            try:
                records = user_env[model_name].search_read(domain, fields_to_read, limit=limit)
                return json.dumps({"count": len(records), "records": records}, default=str)
            except Exception as e:
                return json.dumps({"error": f"Failed to search records: {str(e)}"})

        # --- TOOL: CREATE RECORD ---
        elif tool_name == 'create_record':
            model_name = args.get('model', '').strip()
            values = args.get('values') or {}

            # Security Guardrail 1: Block restricted core / security models
            if model_name in RESTRICTED_MODELS_WRITE:
                return json.dumps({
                    "status": "error",
                    "error_type": "SecurityViolation",
                    "error": f"Keamanan Sistem: Pembuatan data pada model '{model_name}' dilarang demi menjaga keamanan dan integritas ERP."
                })

            # Security Guardrail 2: Block credential & security access fields
            for f_key in values.keys():
                if f_key in RESTRICTED_FIELDS or f_key.startswith('sel_groups_'):
                    return json.dumps({
                        "status": "error",
                        "error_type": "SecurityViolation",
                        "error": f"Keamanan Sistem: Pengisian field '{f_key}' dilarang (kredensial, password, atau hak akses keamanan)."
                    })

            if model_name not in user_env:
                return json.dumps({"error": f"Model '{model_name}' does not exist in Odoo."})

            try:
                # Sanitize values to only include valid Odoo model fields
                valid_fields = user_env[model_name]._fields
                sanitized_values = {k: v for k, v in values.items() if k in valid_fields}

                with self.env.cr.savepoint():
                    new_record = user_env[model_name].create(sanitized_values)
                    base_url = user_env['ir.config_parameter'].sudo().get_param('web.base.url', '')
                    record_url = f"{base_url}/web#id={new_record.id}&model={model_name}&view_type=form"

                    return json.dumps({
                        "status": "success",
                        "id": new_record.id,
                        "display_name": new_record.display_name or f"#{new_record.id}",
                        "model": model_name,
                        "url": record_url,
                        "message": f"Successfully created {model_name} record #{new_record.display_name or new_record.id}."
                    })
            except (AccessError, UserError) as e:
                return json.dumps({"status": "error", "error_type": type(e).__name__, "error": str(e)})
            except Exception as e:
                _logger.exception("Unexpected error creating record via AI tool")
                return json.dumps({"status": "error", "error": str(e)})

        # --- TOOL: EXECUTE MODEL METHOD / BUTTON CLICK ---
        elif tool_name == 'execute_model_method':
            model_name = args.get('model', '').strip()
            record_id = int(args.get('record_id', 0))
            method_name = args.get('method_name', '').strip()

            # Security Guardrail 1: Block restricted models
            if model_name in RESTRICTED_MODELS_WRITE:
                return json.dumps({
                    "status": "error",
                    "error_type": "SecurityViolation",
                    "error": f"Keamanan Sistem: Eksekusi tombol/metode pada model '{model_name}' dilarang demi keamanan sistem."
                })

            # Security Guardrail 2: Block dangerous module lifecycle & password methods
            method_lower = method_name.lower()
            if (method_name in RESTRICTED_METHODS or
                any(kw in method_lower for kw in ('uninstall', 'upgrade', 'install', 'reset_password', 'change_password'))):
                return json.dumps({
                    "status": "error",
                    "error_type": "SecurityViolation",
                    "error": f"Keamanan Sistem: Tombol/metode '{method_name}' dilarang dieksekusi oleh AI Assistant (termasuk instalasi/uninstal modul dan perubahan password)."
                })

            if model_name not in user_env:
                return json.dumps({"error": f"Model '{model_name}' does not exist in Odoo."})

            if not record_id:
                return json.dumps({"error": "Valid record_id is required."})

            if not method_name:
                return json.dumps({"error": "Method name is required."})

            # Prohibit private or dangerous core methods
            if method_name.startswith('_') or method_name in ('unlink', 'read', 'write', 'create', 'search', 'fields_get'):
                return json.dumps({"error": f"Security Violation: Method '{method_name}' cannot be called as an action button."})

            record = user_env[model_name].browse(record_id)
            if not record.exists():
                return json.dumps({"error": f"Record #{record_id} of model '{model_name}' was not found."})

            if not hasattr(record, method_name) or not callable(getattr(record, method_name)):
                return json.dumps({"error": f"Method '{method_name}' does not exist on model '{model_name}'."})

            try:
                with self.env.cr.savepoint():
                    method_func = getattr(record, method_name)
                    action_res = method_func()

                    base_url = user_env['ir.config_parameter'].sudo().get_param('web.base.url', '')
                    record_url = f"{base_url}/web#id={record.id}&model={model_name}&view_type=form"

                    state_val = getattr(record, 'state', None)
                    state_info = f", status sekarang adalah '{state_val}'" if state_val else ""

                    return json.dumps({
                        "status": "success",
                        "message": f"Berhasil mengeksekusi button/metode '{method_name}' pada {model_name} #{record.display_name or record.id}{state_info}.",
                        "url": record_url
                    })
            except (AccessError, UserError) as e:
                return json.dumps({"status": "error", "error_type": type(e).__name__, "error": str(e)})
            except Exception as e:
                _logger.exception("Unexpected error executing button method via AI tool")
                return json.dumps({"status": "error", "error": str(e)})

        # --- TOOL: READ-ONLY SQL QUERY ---
        elif tool_name == 'query_database_readonly':
            raw_query = args.get('query', '').strip().rstrip(';').strip()
            if not raw_query:
                return json.dumps({"error": "Empty SQL query."})

            # Security Guardrail 1: Must begin with SELECT or WITH
            query_lower = raw_query.lower()
            if not (query_lower.startswith('select') or query_lower.startswith('with')):
                return json.dumps({"error": "Security Violation: Only SELECT statements are permitted."})

            # Security Guardrail 2: Reject destructive keywords
            if FORBIDDEN_SQL_KEYWORDS.search(raw_query):
                return json.dumps({"error": "Security Violation: Query contains prohibited SQL modification keywords."})

            # Security Guardrail 3: Reject queries targeting sensitive auth fields
            if SENSITIVE_SQL_COLUMNS.search(raw_query):
                return json.dumps({"error": "Security Violation: Access to authentication and secret columns is restricted."})

            # Limit safety enforcement
            if 'limit' not in query_lower:
                raw_query = f"{raw_query} LIMIT 50"

            try:
                with self.env.cr.savepoint():
                    self.env.cr.execute(raw_query)
                    columns = [desc[0] for desc in self.env.cr.description] if self.env.cr.description else []
                    rows = self.env.cr.fetchall()

                    result_data = [dict(zip(columns, row)) for row in rows[:50]]
                    return json.dumps({"total_rows": len(result_data), "data": result_data}, default=str)
            except Exception as e:
                return json.dumps({"error": f"SQL Execution Error: {str(e)}"})

        return json.dumps({"error": f"Tool '{tool_name}' is not recognized."})

    @api.model
    def _extract_executed_actions(self, messages):
        """Collect a human-readable list of executed tool calls from the message log."""
        actions = []
        tool_names = {
            'get_model_fields': 'Memeriksa struktur model',
            'search_read_records': 'Mencari data record',
            'create_record': 'Membuat record baru',
            'execute_model_method': 'Menekan tombol/metode aksi',
            'query_database_readonly': 'Menjalankan query analitik',
        }
        for msg in messages:
            if msg.get('role') != 'tool':
                continue
            name = (msg.get('name') or '').strip()
            label = tool_names.get(name, name)
            actions.append(label)
        return actions

    @api.model
    def _notify_step_status(self, user_id, channel_id, bot_partner_id, func_name, func_args):
        """Push a lightweight 'step' notification into the chat so the user sees progress."""
        step_labels = {
            'get_model_fields': 'Memeriksa struktur model',
            'search_read_records': 'Mencari data record',
            'create_record': 'Membuat record baru',
            'execute_model_method': 'Menekan tombol/metode aksi',
            'query_database_readonly': 'Menjalankan query analitik',
        }
        label = step_labels.get(func_name, func_name)
        detail = ''
        try:
            args = json.loads(func_args) if isinstance(func_args, str) else (func_args or {})
            model = args.get('model') or ''
            if model:
                detail = f" <code>{model}</code>"
            if func_name == 'query_database_readonly':
                detail = ' <code>SELECT ...</code>'
            if func_name == 'search_read_records' and args.get('domain'):
                detail = f" <code>{model}</code> domain <code>{args.get('domain')}</code>"
            if func_name == 'create_record':
                detail = f" <code>{model}</code>"
            if func_name == 'execute_model_method':
                detail = f" <code>{args.get('method_name')}</code> pada <code>{model}</code> #{args.get('record_id')}"
        except Exception:
            pass

        try:
            channel = self.env['discuss.channel'].sudo().browse(channel_id)
            if channel.exists():
                channel.message_post(
                    author_id=bot_partner_id,
                    body=Markup(f"<p class='text-muted' style='font-size:0.9em;'><i>⏳ {label}{detail}…</i></p>"),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )
                self.env.cr.commit()
        except Exception:
            _logger.debug('Step status notification failed (non-blocking)')

    @api.model
    def process_chat_message(self, user_id, channel_id, user_prompt):
        """Orchestrates LLM query, multi-turn tool calling loop, and returns final HTML reply."""
        channel = self.env['discuss.channel'].browse(channel_id)
        user = self.env['res.users'].browse(user_id)
        company = user.company_id or self.env.company

        config = self.get_ai_config(company)
        endpoint = config['endpoint']
        api_key = config['api_key']
        model = config['model']
        temperature = config['temperature']
        max_history = config['max_history']

        if not endpoint or not api_key:
            return (
                "<p>⚠️ <b>AI Assistant tidak dapat merespons:</b> "
                "Base URL atau API Key belum dikonfigurasi di <i>General Settings &gt; AI Assistant</i>.</p>"
            )

        chat_url = f"{endpoint}/chat/completions" if not endpoint.endswith('/chat/completions') else endpoint
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }

        # 1. System Prompt Context
        system_content = self.build_system_context(user, company)
        messages = [{"role": "system", "content": system_content}]

        # 2. Conversation History from Channel
        history_records = channel.message_ids.filtered(
            lambda m: m.message_type == 'comment' and m.body
        ).sorted(key=lambda m: m.id)

        # Take last N messages before the current one
        bot_partner = self.env.ref('ai_discuss_assistant.partner_ai_assistant', raise_if_not_found=False)
        bot_partner_id = bot_partner.id if bot_partner else 0

        recent_msgs = history_records[-max_history:]
        for msg in recent_msgs:
            clean_body = html2plaintext(msg.body or '').strip()
            if not clean_body:
                continue
            role = "assistant" if msg.author_id.id == bot_partner_id else "user"
            messages.append({"role": role, "content": clean_body})

        # Append latest prompt if not already last
        clean_user_prompt = html2plaintext(user_prompt or '').strip()
        if not messages or messages[-1].get("content") != clean_user_prompt:
            messages.append({"role": "user", "content": clean_user_prompt})

        tools = self.get_tool_definitions(
            enable_tools=config['enable_tools'],
            enable_sql=config['enable_sql']
        )

        max_turns = 15
        force_summary_turns = max_turns - 1
        current_turn = 0

        while current_turn < max_turns:
            current_turn += 1
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "stream": False,
            }
            if tools:
                if current_turn >= force_summary_turns:
                    # Final turns: force the assistant to wrap up in natural language
                    payload["tool_choice"] = "none"
                    messages.append({
                        "role": "user",
                        "content": (
                            "Ringkas sekarang dalam Bahasa Indonesia apa yang sudah kamu temukan dan/atau kerjakan. "
                            "Jika tindakan belum berhasil, jelaskan alasan spesifiknya (misalnya field tidak ditemukan, "
                            "hak akses ditolak, atau metode yang benar) dan saran langkah manual yang bisa dilakukan user. "
                            "Jangan memanggil tool lagi."
                        ),
                    })
                else:
                    payload["tools"] = tools
                    payload["tool_choice"] = "auto"

            try:
                resp = requests.post(chat_url, json=payload, headers=headers, timeout=60)
                if resp.status_code != 200:
                    _logger.error("AI Assistant API error HTTP %s: %s", resp.status_code, resp.text)
                    return f"<p>❌ <b>Error AI Gateway (HTTP {resp.status_code}):</b> {resp.text[:300]}</p>"

                res_json = resp.json()
                choice = res_json.get('choices', [{}])[0]
                message_resp = choice.get('message', {})
                tool_calls = message_resp.get('tool_calls')

                # If no tool calls, return final response
                if not tool_calls:
                    final_content = (message_resp.get('content') or '').strip()
                    if not final_content:
                        # Model gave an empty message (happens on some routers when forced to summarize):
                        # produce a useful fallback summary instead of a silent "(no reply)".
                        actions = self._extract_executed_actions(messages)
                        if actions:
                            lines = ''.join(f"<li>{a}</li>" for a in actions[-6:])
                            return (
                                "<p>Selesai memproses permintaan Anda. Ringkasan langkah yang sudah saya jalankan:</p>"
                                f"<ul>{lines}</ul>"
                                "<p>Silakan cek hasilnya. Jika hasilnya belum sesuai, beri tahu saya detail yang kurang.</p>"
                            )
                        return "<p>Maaf, saya belum berhasil menyusun jawaban dari model. Coba ulangi perintah dengan lebih spesifik.</p>"

                    formatted_reply = final_content.replace('\n', '<br/>')
                    return formatted_reply

                # If tool calls returned, append assistant message to conversation history
                messages.append(message_resp)

                # Execute each tool call and append tool role response
                for tool_call in tool_calls:
                    call_id = tool_call.get('id')
                    func = tool_call.get('function', {})
                    func_name = func.get('name')
                    func_args = func.get('arguments')

                    _logger.info("AI Assistant executing tool: %s with args: %s", func_name, func_args)
                    self._notify_step_status(user_id, channel_id, bot_partner_id, func_name, func_args)
                    tool_output = self.execute_tool(user_id, func_name, func_args)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": call_id,
                        "content": tool_output
                    })

            except requests.exceptions.Timeout:
                return "<p>⏳ <b>Timeout:</b> Server AI Gateway membutuhkan waktu terlalu lama untuk merespons.</p>"
            except Exception as e:
                _logger.exception("AI Assistant processing error")
                return f"<p>❌ <b>Terjadi kesalahan pada AI Assistant:</b> {str(e)}</p>"

        return "<p>⚠️ <i>Percakapan mencapai batas maksimum iterasi tool calling.</i></p>"
