import sys, tempfile, unittest, os
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from aihoop import auth, api
from fastapi.testclient import TestClient

class LoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.old=auth.DATA; auth.DATA=Path(self.tmp.name)
        self.env=patch.dict(os.environ, {'AIHOOP_ACCOUNTS':'','AIHOOP_INTERNAL_TOKEN':''})
        self.env.start();auth.save_account('reviewer','a-long-test-password')
        self.c=TestClient(api.app)
    def tearDown(self):
        self.c.close();auth.DATA=self.old;self.env.stop();self.tmp.cleanup()
    def login(self):
        r=self.c.post('/api/login',json={'username':'reviewer','password':'a-long-test-password'})
        self.assertEqual(r.status_code,200,r.text);return self.c.cookies.get(auth.COOKIE_NAME)
    def test_requires_login_including_local(self):
        self.assertFalse(auth.internal_ok('127.0.0.1'))
        self.assertEqual(self.c.get('/api/jobs').status_code,401)
        r=self.c.get('/web/index.html',follow_redirects=False)
        self.assertEqual(r.status_code,302)
        self.assertEqual(self.c.get('/web/login.html').status_code,200)
        self.assertEqual(self.c.get('/api/media/anything/a.mp4').status_code,401)
    def test_login_cookie_logout_revokes(self):
        token=self.login()
        self.assertEqual(self.c.get('/api/me').json()['username'],'reviewer')
        self.assertEqual(self.c.post('/api/logout').status_code,200)
        self.assertIsNone(auth.read_session(token))
    def test_password_reset_and_account_removal(self):
        token=self.login();auth.save_account('reviewer','another-password')
        self.assertIsNone(auth.read_session(token))
        token=auth.issue_session('reviewer');(auth.DATA/'accounts.json').write_text('{}')
        self.assertIsNone(auth.read_session(token))
    def test_expired_and_malformed(self):
        for token in ('☃.bad', 'x'*1000, 'nope', 'a'*32):
            self.assertIsNone(auth.read_session(token))
        token=self.login()
        with auth._db() as c:c.execute('UPDATE sessions SET expires=0')
        self.assertIsNone(auth.read_session(token))
    def test_rate_limit(self):
        for _ in range(10):
            self.assertEqual(self.c.post('/api/login',json={'username':'nobody','password':'bad'}).status_code,401)
        self.assertEqual(self.c.post('/api/login',json={'username':'nobody','password':'bad'}).status_code,429)
    def test_cross_site_write(self):
        self.login()
        self.assertEqual(self.c.post('/api/logout',headers={'origin':'https://other.invalid'}).status_code,403)
    def test_websocket_requires_login(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect):
            with self.c.websocket_connect('/api/jobs/test/ws'):pass
    def test_internal_requires_loopback_and_token(self):
        with patch.dict(os.environ,{'AIHOOP_INTERNAL_TOKEN':'test-token'}):
            self.assertTrue(auth.internal_ok('127.0.0.1','test-token'))
            self.assertFalse(auth.internal_ok('127.0.0.1','wrong'))
            self.assertFalse(auth.internal_ok('192.168.0.2','test-token'))
    def test_secure_cookie(self):
        with TestClient(api.app,base_url='https://testserver') as c:
            r=c.post('/api/login',json={'username':'reviewer','password':'a-long-test-password'})
            for attribute in ('HttpOnly','Secure','SameSite=lax'):
                self.assertIn(attribute,r.headers['set-cookie'])

if __name__=='__main__':unittest.main()
