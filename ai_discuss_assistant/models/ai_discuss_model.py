# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AiDiscussModel(models.Model):
    _name = 'ai.discuss.model'
    _description = 'Available AI Model'
    _order = 'name asc'

    name = fields.Char(
        string='Model Identifier',
        required=True,
        index=True,
        help='Technical identifier of the model (e.g. gpt-4o-mini, ag/gemini-3.8-flash-low)'
    )
    owned_by = fields.Char(
        string='Owned By / Provider',
        help='Provider or architecture of the model (e.g. openai, google, combo)'
    )
    active = fields.Boolean(
        string='Active',
        default=True
    )

    _sql_constraints = [
        ('name_uniq', 'unique(name)', 'Model identifier must be unique!')
    ]

    def name_get(self):
        result = []
        for record in self:
            label = f"{record.name} ({record.owned_by})" if record.owned_by else record.name
            result.append((record.id, label))
        return result
