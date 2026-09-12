import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

import requests
import index as app


class CheckinTests(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        network = patch.object(requests.sessions.Session, "request",
                               side_effect=AssertionError("离线测试禁止网络请求"))
        network.start()
        self.addCleanup(network.stop)
        self.account = {"username": "test-account", "password": "test-password"}

    def test_hardcoded_fallback(self):
        with patch.object(app, "accounts", [self.account]):
            self.assertEqual(app.load_config({})["accounts"], [self.account])

    def test_environment_replaces_accounts_without_trimming_password(self):
        account = {"username": "env-account", "password": " p&'\\\" "}
        with patch.object(app, "accounts", [self.account]):
            config = app.load_config({"TY_ACCOUNTS": json.dumps([account])})
        self.assertEqual(config["accounts"], [account])

    def test_invalid_environment_never_falls_back(self):
        for raw in ("", "not-json", "null", "{}", "[]", "[{}]",
                    '[{"username":"a","password":123}]'):
            with self.subTest(raw=raw), patch.object(app, "accounts", [self.account]):
                with self.assertRaises(ValueError):
                    app.load_config({"TY_ACCOUNTS": raw})

    def test_telegram_source_is_atomic(self):
        env = {"TY_ACCOUNTS": json.dumps([self.account]), "TG_BOT_TOKEN": "new-token"}
        with patch.object(app, "TG_BOT_TOKEN", "old-token"), patch.object(app, "TG_CHAT_ID", "old-chat"):
            config = app.load_config(env)
            self.assertEqual(config["chat_id"], "")
            self.assertEqual(config["notification"], "incomplete")
            env["TG_BOT_TOKEN"] = ""
            self.assertEqual(app.load_config(env)["notification"], "disabled")

    def test_telegram_hardcoded_pair(self):
        with patch.object(app, "accounts", [self.account]), patch.object(app, "TG_BOT_TOKEN", "token"), patch.object(app, "TG_CHAT_ID", "chat"):
            config = app.load_config({})
        self.assertEqual((config["token"], config["chat_id"], config["notification"]),
                         ("token", "chat", "ready"))

    def test_configuration_is_read_again_each_invocation(self):
        with patch.dict(app.os.environ, {"TY_ACCOUNTS": json.dumps([self.account])}, clear=True):
            self.assertEqual(app.load_config()["accounts"][0]["username"], "test-account")
            app.os.environ["TY_ACCOUNTS"] = "[]"
            with self.assertRaises(ValueError):
                app.load_config()

    def test_config_error_stops_before_login(self):
        with patch.dict(app.os.environ, {"TY_ACCOUNTS": "bad-json"}, clear=True), patch.object(app, "login") as login:
            body = json.loads(app.main_handler({}, None)["body"])
        self.assertFalse(body["ok"])
        self.assertEqual(body["notification"], "not_attempted")
        self.assertNotIn("bad-json", body["config_error"])
        login.assert_not_called()

    def test_single_sign_request_and_response_states(self):
        for state in (False, True, "false", "true", None, 0, 1):
            with self.subTest(state=state):
                session = Mock(cloud189_session_key="test-key")
                session.get.return_value.status_code = 200
                session.get.return_value.json.return_value = {"isSign": state, "netdiskBonus": 63}
                valid = state is False or state is True or isinstance(state, str)
                if valid:
                    app.user_sign(session)
                else:
                    with self.assertRaises(app.LoginError):
                        app.user_sign(session)
                session.get.assert_called_once()
                args, kwargs = session.get.call_args
                self.assertEqual(args[0], app.WEB_URL + "/mkt/userSign.action")
                self.assertEqual(kwargs["params"]["sessionKey"], "test-key")
                self.assertNotIn("Host", kwargs["headers"])
                self.assertEqual(kwargs["timeout"], app.TIMEOUT)

    def test_missing_fields_are_failure(self):
        session = Mock(cloud189_session_key="test-key")
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {}
        result = app.do_checkin(session, "masked")
        self.assertEqual(result["status"], "failed")
        session.get.assert_called_once()

    def test_no_lottery_or_false_failure_after_sign(self):
        with patch.object(app, "user_sign", return_value={"isSign": False, "netdiskBonus": 63}):
            result = app.do_checkin(Mock(), "masked")
        self.assertEqual(result["status"], "signed")
        self.assertIsNone(result["error"])
        self.assertNotIn("lottery1", result)

    def test_timeout_has_no_secret_and_no_retry(self):
        session = Mock(cloud189_session_key="test-key")
        session.get.side_effect = requests.Timeout("https://example.invalid/?sessionKey=secret")
        result = app.do_checkin(session, "masked")
        self.assertNotIn("secret", result["error"])
        session.get.assert_called_once()

    def test_sessions_close_and_failed_account_does_not_stop_next(self):
        session = Mock()
        env = {"TY_ACCOUNTS": json.dumps([self.account, self.account])}
        with patch.dict(app.os.environ, env, clear=True), patch.object(app, "login", side_effect=[app.LoginError("登录被拒绝"), session]), patch.object(app, "user_sign", return_value={"isSign": True, "netdiskBonus": 0}), patch.object(app.time, "sleep"):
            result = app.main()
        self.assertEqual(result["counts"], {"signed": 0, "already_signed": 1, "failed": 1})
        self.assertFalse(result["ok"])
        session.close.assert_called_once()

    def test_notification_failure_does_not_change_sign_result(self):
        env = {"TY_ACCOUNTS": json.dumps([self.account]), "TG_BOT_TOKEN": "test-token", "TG_CHAT_ID": "test-chat"}
        account_result = {"username": "masked", "status": "signed", "signin": "成功", "error": None}
        with patch.dict(app.os.environ, env, clear=True), patch.object(app, "process_account", return_value=account_result), patch.object(app, "send_telegram_notification", return_value=False):
            result = app.main()
        self.assertTrue(result["ok"])
        self.assertEqual(result["notification"], "failed")

    def test_telegram_uses_plain_text(self):
        response = Mock(status_code=200)
        response.json.return_value = {"ok": True}
        with patch.object(app.requests, "post", return_value=response) as post:
            self.assertTrue(app.send_telegram_notification("text_with_[symbols]", "test-token", "test-chat"))
        self.assertNotIn("parse_mode", post.call_args[1]["json"])


if __name__ == "__main__":
    unittest.main()
