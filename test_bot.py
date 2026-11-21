import smtplib
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import bot


class BotTests(unittest.TestCase):
    def test_mx_only_domain_and_null_mx(self):
        for exchange, expected in [("mail.example.org.", True), (".", False)]:
            with patch.object(bot.dns.resolver, "resolve", return_value=[SimpleNamespace(exchange=exchange)]) as resolve:
                self.assertIs(bot.check_mx("example.org"), expected)
                resolve.assert_called_once_with("example.org", "MX", lifetime=5)

    def test_dns_timeout_is_not_a_dead_domain(self):
        with patch.object(bot.dns.resolver, "resolve", side_effect=bot.dns.exception.Timeout):
            self.assertIsNone(bot.check_mx("example.org"))

    def test_auth_check_never_submits(self):
        server = Mock()
        with patch.dict(bot.os.environ, {"GMAIL_ADDRESS": "sender@example.org", "GMAIL_APP_PASSWORD": "abcd efgh"}), \
             patch.object(bot, "connect_gmail", return_value=server) as connect:
            bot.main(check_smtp=True)
        connect.assert_called_once_with("sender@example.org", "abcdefgh")
        server.sendmail.assert_not_called()
        server.close.assert_called_once()

    def test_disconnect_before_sending_leaves_lead_pending(self):
        hotel = {"name": "Test Hotel", "email": "jobs@example.org", "status": "pending", "source_url": "https://example.org/careers"}
        with patch.dict(bot.os.environ, {"GMAIL_ADDRESS": "sender@example.org", "GMAIL_APP_PASSWORD": "mock", "HOTEL_CV_PDF_BASE64": "JVBERi0xLjc="}), \
             patch.object(bot, "load_json", side_effect=[{}, [hotel], []]), \
             patch.object(bot, "check_mx", return_value=True), \
             patch.object(bot, "connect_gmail", side_effect=smtplib.SMTPServerDisconnected), \
             patch.object(bot, "save_json") as save:
            with self.assertRaisesRegex(SystemExit, "lead remains pending"):
                bot.main()
        self.assertEqual(hotel["status"], "pending")
        save.assert_not_called()

    def test_disconnect_during_submission_is_uncertain(self):
        server = Mock()
        server.sendmail.side_effect = smtplib.SMTPServerDisconnected
        with patch.object(bot, "connect_gmail", return_value=server):
            with self.assertRaises(bot.DeliveryUncertain):
                bot.send_email("sender@example.org", "mock", "jobs@example.org", "Test", "Body")
        server.close.assert_called_once()

    def test_cv_is_attached(self):
        from email import message_from_string

        server = Mock()
        cv = b"%PDF-1.7"
        with patch.object(bot, "connect_gmail", return_value=server):
            bot.send_email("sender@example.org", "mock", "jobs@example.org", "Test", "Body", cv=cv)
        message = message_from_string(server.sendmail.call_args.args[2])
        attachment = next(part for part in message.walk() if part.get_filename() == "CV.pdf")
        self.assertEqual(attachment.get_payload(decode=True), cv)

    def test_verified_contacts_import_once(self):
        hotels = []
        self.assertGreater(bot.inject_new_hotels(hotels, []), 0)
        self.assertEqual(bot.inject_new_hotels(hotels, []), 0)
        self.assertTrue(all(lead["source_url"].startswith("https://") for lead in hotels))

    def test_api_auth_check_only_refreshes_token(self):
        with patch.object(bot, "gmail_api_token", return_value="mock") as refresh, \
             patch.object(bot, "send_email") as send:
            bot.main(check_api=True)
        refresh.assert_called_once()
        send.assert_not_called()

    def test_api_sends_without_smtp_and_checks_response(self):
        with patch.object(bot.requests, "post", return_value=Mock(status_code=200)) as post, \
             patch.object(bot, "connect_gmail") as smtp:
            bot.send_email("sender@example.org", "", "jobs@example.org", "Test", "Body", api_token="mock")
            post.return_value.status_code = 408
            with self.assertRaises(bot.DeliveryUncertain):
                bot.send_email("sender@example.org", "", "jobs@example.org", "Test", "Body", api_token="mock")
        self.assertEqual(post.call_args.args[0], "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
        self.assertIn("raw", post.call_args.kwargs["json"])
        smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
