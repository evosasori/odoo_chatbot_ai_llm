# -*- coding: utf-8 -*-
import json
import time
import requests
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ai_discuss_endpoint = fields.Char(
        string='AI Assistant Base URL',
        config_parameter='ai_discuss.endpoint',
        help='OpenAI-compatible API base URL (e.g., https://api.openai.com/v1 or https://9router.triadiputra.my.id/v1)'
    )

    ai_discuss_api_key = fields.Char(
        string='AI Assistant API Key',
        config_parameter='ai_discuss.api_key',
        help='Bearer API Key for OpenAI-compatible endpoint.'
    )

    ai_discuss_model_id = fields.Many2one(
        'ai.discuss.model',
        string='Select AI Model',
        help='Choose an active AI model fetched dynamically from your API Gateway.'
    )

    ai_discuss_model = fields.Char(
        string='AI Assistant Model Code',
        config_parameter='ai_discuss.model',
        default='gpt-4o-mini',
        help='Model identifier string (e.g., gpt-4o-mini, ag/gemini-3.8-flash-low).'
    )

    ai_discuss_temperature = fields.Float(
        string='Temperature',
        config_parameter='ai_discuss.temperature',
        default=0.5,
        help='Sampling temperature (0.0 = deterministic, 1.0 = creative).'
    )

    ai_discuss_max_history = fields.Integer(
        string='Max History Messages',
        config_parameter='ai_discuss.max_history',
        default=8,
        help='Number of previous chat messages to provide as conversation context.'
    )

    ai_discuss_enable_tools = fields.Boolean(
        string='Enable ORM Actions (Create/Read)',
        config_parameter='ai_discuss.enable_tools',
        default=True,
        help='Allow AI to inspect Odoo models and create/search records via Odoo ORM under user privileges.'
    )

    ai_discuss_enable_sql = fields.Boolean(
        string='Enable Read-Only PostgreSQL Queries',
        config_parameter='ai_discuss.enable_sql',
        default=True,
        help='Allow AI to execute safe read-only SELECT queries for analytical questions.'
    )

    ai_discuss_system_prompt = fields.Text(
        string='Custom System Instructions',
        help='Additional instructions given to the AI Assistant.'
    )

    @api.onchange('ai_discuss_model_id')
    def _onchange_ai_discuss_model_id(self):
        if self.ai_discuss_model_id:
            self.ai_discuss_model = self.ai_discuss_model_id.name

    @api.model
    def get_values(self):
        res = super().get_values()
        ICP = self.env['ir.config_parameter'].sudo()
        current_model_name = ICP.get_param('ai_discuss.model', default='gpt-4o-mini')
        model_rec = self.env['ai.discuss.model'].search([('name', '=', current_model_name)], limit=1)

        res.update(
            ai_discuss_system_prompt=ICP.get_param('ai_discuss.system_prompt', default=''),
            ai_discuss_model_id=model_rec.id if model_rec else False,
            ai_discuss_model=current_model_name,
        )
        return res

    def set_values(self):
        super().set_values()
        ICP = self.env['ir.config_parameter'].sudo()
        ICP.set_param('ai_discuss.system_prompt', self.ai_discuss_system_prompt or '')

        selected_model = self.ai_discuss_model_id.name if self.ai_discuss_model_id else self.ai_discuss_model
        if selected_model:
            ICP.set_param('ai_discuss.model', selected_model)

    def action_fetch_ai_models(self):
        """Fetch available models list dynamically from the AI Gateway endpoint."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        company = self.env.company

        endpoint = (self.ai_discuss_endpoint or ICP.get_param('ai_discuss.endpoint') or getattr(company, 'custom_ai_endpoint', '') or '').rstrip('/')
        api_key = self.ai_discuss_api_key or ICP.get_param('ai_discuss.api_key') or getattr(company, 'custom_ai_api_key', '')

        if not endpoint:
            raise UserError("Base URL endpoint is required. Please fill in the AI Assistant Base URL first.")
        if not api_key:
            raise UserError("API Key is required. Please fill in the AI Assistant API Key first.")

        models_url = f"{endpoint}/models"
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }

        try:
            resp = requests.get(models_url, headers=headers, timeout=15)
            if resp.status_code != 200:
                raise UserError(f"Failed to fetch models from API (HTTP {resp.status_code}): {resp.text[:300]}")

            data = resp.json()
            raw_models = data.get('data', [])
            if not raw_models and isinstance(data, list):
                raw_models = data

            if not raw_models:
                raise UserError("API returned successfully, but no models list was found in response.")

            ModelObj = self.env['ai.discuss.model'].sudo()
            count_new = 0
            count_updated = 0

            for m in raw_models:
                m_id = m.get('id') if isinstance(m, dict) else str(m)
                owned_by = m.get('owned_by', '') if isinstance(m, dict) else ''
                if not m_id:
                    continue

                existing = ModelObj.search([('name', '=', m_id)], limit=1)
                if existing:
                    existing.write({'owned_by': owned_by, 'active': True})
                    count_updated += 1
                else:
                    ModelObj.create({'name': m_id, 'owned_by': owned_by, 'active': True})
                    count_new += 1

            # Auto-link current model if exists
            current_model = self.ai_discuss_model or ICP.get_param('ai_discuss.model')
            match_rec = ModelObj.search([('name', '=', current_model)], limit=1)
            if match_rec:
                self.ai_discuss_model_id = match_rec.id

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Models Fetched Successfully! 🚀',
                    'message': f'Total models synced: {count_new + count_updated} (New: {count_new}, Existing: {count_updated}). Silakan pilih model dari dropdown.',
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            _logger.exception("Failed to fetch models from AI endpoint")
            raise UserError(f"Error fetching models: {str(e)}")

    def action_test_ai_discuss_connection(self):
        """Test connection to the AI Assistant endpoint and verify response latency."""
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        company = self.env.company

        endpoint = (self.ai_discuss_endpoint or ICP.get_param('ai_discuss.endpoint') or getattr(company, 'custom_ai_endpoint', '') or '').rstrip('/')
        api_key = self.ai_discuss_api_key or ICP.get_param('ai_discuss.api_key') or getattr(company, 'custom_ai_api_key', '')
        model = (
            self.ai_discuss_model_id.name if self.ai_discuss_model_id
            else (self.ai_discuss_model or ICP.get_param('ai_discuss.model') or getattr(company, 'custom_ai_model', '') or 'gpt-4o-mini')
        )

        if not endpoint:
            raise UserError("Base URL endpoint is required. Please fill in the AI Assistant Base URL.")
        if not api_key:
            raise UserError("API Key is required. Please fill in the AI Assistant API Key.")

        chat_url = f"{endpoint}/chat/completions" if not endpoint.endswith('/chat/completions') else endpoint
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': 'You are a test ping responder.'},
                {'role': 'user', 'content': 'Ping test. Reply with: PONG'}
            ],
            'temperature': 0.1,
            'max_tokens': 20,
            'stream': False
        }

        start_time = time.time()
        try:
            response = requests.post(chat_url, json=payload, headers=headers, timeout=20)
            latency_ms = int((time.time() - start_time) * 1000)

            if response.status_code == 200:
                reply = ""
                # Robust response parsing (handles JSON and SSE fallback)
                try:
                    res_data = response.json()
                    reply = res_data.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
                except Exception:
                    # Fallback for gateways that stream SSE even with stream=False
                    raw_lines = response.text.splitlines()
                    for line in raw_lines:
                        if line.startswith('data: ') and not line.strip().endswith('[DONE]'):
                            try:
                                chunk = json.loads(line[6:])
                                delta = chunk.get('choices', [{}])[0].get('delta', {})
                                if 'content' in delta:
                                    reply += delta['content']
                            except Exception:
                                continue

                reply_display = reply or "PONG"
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'AI Assistant Connected! 🚀',
                        'message': f'Endpoint: {endpoint} | Model: {model} | Latency: {latency_ms} ms | Reply: {reply_display}',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': f'Connection Error (HTTP {response.status_code})',
                        'message': response.text[:250],
                        'type': 'danger',
                        'sticky': True,
                    }
                }
        except Exception as e:
            _logger.exception("Failed to connect to AI Assistant endpoint")
            raise UserError(f"Connection failed: {str(e)}")
