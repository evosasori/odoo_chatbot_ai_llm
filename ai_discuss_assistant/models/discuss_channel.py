# -*- coding: utf-8 -*-
import threading
import logging
from odoo import api, models

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    def _message_post_after_hook(self, message, msg_vals):
        res = super()._message_post_after_hook(message, msg_vals)

        bot_partner = self.env.ref('ai_discuss_assistant.partner_ai_assistant', raise_if_not_found=False)
        if not bot_partner:
            return res

        # 1. Prevent infinite loops: Never reply to own messages
        if message.author_id.id == bot_partner.id:
            return res

        # Only process comment messages (ignore system notifications, stage changes, tracking)
        if message.message_type != 'comment':
            return res

        # 2. Check trigger conditions:
        # Condition A: 1-on-1 Direct Chat with AI Assistant
        is_direct_chat = (
            self.channel_type == 'chat' and
            bot_partner in self.channel_member_ids.partner_id
        )
        # Condition B: Mentioned with @AI Assistant in group or public channel
        is_mentioned = bot_partner in message.partner_ids

        if is_direct_chat or is_mentioned:
            db_name = self.env.cr.dbname
            user_id = self.env.user.id
            channel_id = self.id
            raw_body = message.body or ''

            # Trigger live typing indicator to let user know AI is processing
            bot_member = self.channel_member_ids.filtered(lambda m: m.partner_id.id == bot_partner.id)
            if bot_member:
                try:
                    bot_member._notify_typing(True)
                except Exception:
                    pass

            _logger.info(
                "Triggering AI Discuss Assistant for channel %s (user: %s, direct: %s, mentioned: %s)",
                channel_id, user_id, is_direct_chat, is_mentioned
            )

            # 3. Asynchronous Worker Execution
            threading.Thread(
                target=self._async_ai_discuss_worker,
                args=(db_name, user_id, channel_id, raw_body, bot_partner.id),
                daemon=True,
                name=f"AiDiscussWorker-Chan{channel_id}-Msg{message.id}"
            ).start()

        return res

    @classmethod
    def _async_ai_discuss_worker(cls, db_name, user_id, channel_id, message_body, bot_partner_id):
        """Asynchronous worker that interacts with the AI agent and posts the response back."""
        import time
        import odoo
        from odoo import api
        from markupsafe import Markup

        for attempt in range(3):
            try:
                registry = odoo.modules.registry.Registry(db_name)
                with registry.cursor() as cr:
                    env = api.Environment(cr, user_id, {})
                    channel = env['discuss.channel'].browse(channel_id)
                    if not channel.exists():
                        _logger.warning("Channel %s no longer exists for AI Discuss worker.", channel_id)
                        return

                    bot_member = channel.channel_member_ids.filtered(lambda m: m.partner_id.id == bot_partner_id)
                    try:
                        ai_service = env['ai.agent.service']
                        reply_html = ai_service.process_chat_message(user_id, channel_id, message_body)
                    finally:
                        if bot_member:
                            try:
                                bot_member._notify_typing(False)
                            except Exception:
                                pass

                    # Post response as AI Assistant Partner
                    channel.sudo().message_post(
                        author_id=bot_partner_id,
                        body=Markup(reply_html),
                        message_type='comment',
                        subtype_xmlid='mail.mt_comment',
                    )
                    cr.commit()
                    _logger.info("AI Discuss Assistant posted reply to channel %s successfully.", channel_id)
                    break

            except Exception as e:
                if 'could not serialize access' in str(e).lower() and attempt < 2:
                    time.sleep(0.5)
                    continue
                _logger.exception("Error in AI Discuss background worker: %s", str(e))
                break
