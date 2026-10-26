# -*- coding: utf-8 -*-
from . import models


def post_init_hook(env):
    """Auto-create an internal user bound to the AI Assistant partner.

    Odoo's Discuss 'New Message' user picker only lists active res.users,
    so a bare partner is undiscoverable. This hook guarantees the bot is
    chat-ready right after module installation. Idempotent: skips creation
    if a user already exists for the bot partner or the reserved login.
    """
    bot_partner = env.ref('ai_discuss_assistant.partner_ai_assistant', raise_if_not_found=False)
    if not bot_partner:
        return

    Users = env['res.users'].with_context(active_test=False).sudo()
    existing = Users.search([
        '|',
        ('partner_id', '=', bot_partner.id),
        ('login', '=', 'ai_assistant_bot'),
    ], limit=1)
    if existing:
        return

    Users.create({
        'name': 'AI Assistant',
        'login': 'ai_assistant_bot',
        'partner_id': bot_partner.id,
        'active': True,
        'groups_id': [(6, 0, [env.ref('base.group_user').id])],
    })
