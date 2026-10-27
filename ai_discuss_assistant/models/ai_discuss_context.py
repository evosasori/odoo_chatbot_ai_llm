# -*- coding: utf-8 -*-
from odoo import fields, models


class AiDiscussContext(models.Model):
    """Keyword -> model description knowledge base for the AI Assistant.

    When a user's prompt contains a keyword, the matching description is
    injected into the AI's system context so it doesn't have to guess the
    schema of custom models (e.g. SIMRS).
    """
    _name = 'ai.discuss.context'
    _description = 'AI Context Keyword'
    _order = 'keyword asc'

    keyword = fields.Char(
        string='Keyword',
        required=True,
        index=True,
        help='Kata kunci yang akan dicocokkan (case-insensitive) pada pesan user. Contoh: "registrasi"'
    )
    model_name = fields.Char(
        string='Odoo Model',
        help='Nama teknis model Odoo yang relevan, contoh: cdn.registrasi.periksa'
    )
    description = fields.Text(
        string='Keterangan / Deskripsi',
        help='Penjelasan untuk AI: apa model ini, field penting, status/state, dan bagaimana menggunakannya.'
    )
    active = fields.Boolean(
        string='Active',
        default=True
    )
