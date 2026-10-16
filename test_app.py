import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.parser import parse_filename
from app.gdrive import extract_folder_id
from app.mailer import generate_secure_password
from app.database import Base, engine, SessionLocal
from app.models import User, DriveFolder, Movie

class TestFilmsOverWeb(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        from app.auth import get_password_hash
        admin = db.query(User).filter(User.role == "superadmin").first()
        if admin:
            admin.email = "test@gmail.com"
            admin.hashed_password = get_password_hash("1q2w3e4r5t")
            admin.must_change_password = True
            db.commit()
        else:
            from app.auth import init_default_users
            init_default_users(db)
        db.close()
        cls.client = TestClient(app)

    def test_01_filename_parser(self):
        # Test HEVC / 4K
        res1 = parse_filename("Oppenheimer.2023.IMAX.2160p.UHD.HDR.HEVC.Atmos.mkv")
        self.assertEqual(res1["title"], "Oppenheimer")
        self.assertEqual(res1["year"], 2023)
        self.assertEqual(res1["codec"], "HEVC")
        self.assertEqual(res1["resolution"], "4K UHD")

        # Test AV1 / 1080p
        res2 = parse_filename("Spider-Man.Across.the.Spider-Verse.2023.1080p.WEBRip.AV1.mp4")
        self.assertEqual(res2["title"], "Spider-Man Across the Spider-Verse")
        self.assertEqual(res2["year"], 2023)
        self.assertEqual(res2["codec"], "AV1")
        self.assertEqual(res2["resolution"], "1080p")

        # Test standard title with year in parens
        res3 = parse_filename("Interstellar (2014) [1080p] [x265].mp4")
        self.assertEqual(res3["title"], "Interstellar")
        self.assertEqual(res3["year"], 2014)
        self.assertEqual(res3["codec"], "HEVC")

    def test_02_gdrive_folder_id_extractor(self):
        url1 = "https://drive.google.com/drive/folders/1aBcDeFgHiJkLmNoPqRsTuVwXyZ?usp=sharing"
        self.assertEqual(extract_folder_id(url1), "1aBcDeFgHiJkLmNoPqRsTuVwXyZ")

        raw_id = "1aBcDeFgHiJkLmNoPqRsTuVwXyZ"
        self.assertEqual(extract_folder_id(raw_id), "1aBcDeFgHiJkLmNoPqRsTuVwXyZ")

        url2 = "https://drive.google.com/drive/u/0/folders/1234567890abcdefghijk_lmnop"
        self.assertEqual(extract_folder_id(url2), "1234567890abcdefghijk_lmnop")

    def test_03_password_generator(self):
        pw = generate_secure_password(12)
        self.assertEqual(len(pw), 12)
        self.assertTrue(any(c.isupper() for c in pw))
        self.assertTrue(any(c.islower() for c in pw))
        self.assertTrue(any(c.isdigit() for c in pw))

    def test_04_auth_and_login_first_time(self):
        # Attempt login with default SuperAdmin test@gmail.com / 1q2w3e4r5t
        resp = self.client.post("/login", data={
            "email": "test@gmail.com",
            "password": "1q2w3e4r5t",
            "next": "/"
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        # Should redirect to /change-password on first login
        self.assertIn("/change-password", resp.headers.get("location", ""))
        self.assertIn("fow_token", resp.cookies)

        # GET /change-password should render the setup form
        cp_page = self.client.get("/change-password")
        self.assertEqual(cp_page.status_code, 200)
        self.assertIn(b"Set Admin Email & Password", cp_page.content)
        self.assertIn(b"test@gmail.com", cp_page.content)

    def test_05_guest_restriction(self):
        # Create a guest in DB
        db = SessionLocal()
        guest = db.query(User).filter(User.email == "testguest@example.com").first()
        if not guest:
            from app.auth import get_password_hash
            guest = User(
                email="testguest@example.com",
                name="Guest Tester",
                hashed_password=get_password_hash("GuestPass@123"),
                role="guest",
                must_change_password=False,
                is_active=True
            )
            db.add(guest)
            db.commit()
        else:
            guest.must_change_password = False
            db.commit()
        db.close()

        # Login as Guest
        guest_client = TestClient(app)
        login_resp = guest_client.post("/login", data={
            "email": "testguest@example.com",
            "password": "GuestPass@123",
            "next": "/"
        }, follow_redirects=True)
        self.assertEqual(login_resp.status_code, 200)

        # Guest tries to access SuperAdmin settings -> should be 403 Forbidden
        admin_resp = guest_client.get("/superadmin/settings")
        self.assertEqual(admin_resp.status_code, 403)

        # Guest tries to access Admin folders -> should be 403 Forbidden
        folder_resp = guest_client.get("/admin/folders")
        self.assertEqual(folder_resp.status_code, 403)

        # Guest can access home and catalog
        home_resp = guest_client.get("/")
        self.assertEqual(home_resp.status_code, 200)
        catalog_resp = guest_client.get("/movies")
        self.assertEqual(catalog_resp.status_code, 200)

    def test_06_superadmin_change_credentials_flow(self):
        admin_client = TestClient(app)
        # Login with default credentials
        admin_client.post("/login", data={
            "email": "test@gmail.com",
            "password": "1q2w3e4r5t",
            "next": "/"
        })

        # Submit change password & email form
        new_email = "myadmin@example.com"
        new_pw = "MySecureAdminPass2026!"
        try:
            change_resp = admin_client.post("/change-password", data={
                "email": new_email,
                "current_password": "1q2w3e4r5t",
                "new_password": new_pw,
                "confirm_password": new_pw
            }, follow_redirects=False)
            self.assertEqual(change_resp.status_code, 302)
            self.assertIn("/superadmin/settings?setup_complete=1", change_resp.headers.get("location", ""))

            # Follow to settings
            settings_resp = admin_client.get("/superadmin/settings?setup_complete=1")
            self.assertEqual(settings_resp.status_code, 200)
            self.assertIn(b"SuperAdmin Credentials Updated Successfully", settings_resp.content)

            # Verify db updated and must_change_password is now False
            db = SessionLocal()
            admin_user = db.query(User).filter(User.email == new_email).first()
            self.assertIsNotNone(admin_user)
            self.assertEqual(admin_user.role, "superadmin")
            self.assertFalse(admin_user.must_change_password)
            db.close()
        finally:
            # Reset back to default test@gmail.com / 1q2w3e4r5t for persistent repeatability
            db = SessionLocal()
            admin_user = db.query(User).filter(User.role == "superadmin").first()
            if admin_user:
                from app.auth import get_password_hash
                admin_user.email = "test@gmail.com"
                admin_user.hashed_password = get_password_hash("1q2w3e4r5t")
                admin_user.must_change_password = True
                db.commit()
            db.close()

    def test_07_superadmin_env_vars(self):
        import os
        from app.auth import init_default_users, verify_password
        from app.config import settings

        old_email_env = os.environ.get("SuperAdminEmail")
        old_pw_env = os.environ.get("SuperAdminPassword")
        try:
            os.environ["SuperAdminEmail"] = "envadmin@customcinema.com"
            os.environ["SuperAdminPassword"] = "EnvPassSecret2026!"
            settings.SUPERADMIN_EMAIL = "envadmin@customcinema.com"
            settings.SUPERADMIN_PASSWORD = "EnvPassSecret2026!"
            settings.SUPERADMIN_ENV_SET = True

            db = SessionLocal()
            init_default_users(db)
            admin = db.query(User).filter(User.role == "superadmin").first()
            self.assertIsNotNone(admin)
            self.assertEqual(admin.email, "envadmin@customcinema.com")
            self.assertTrue(verify_password("EnvPassSecret2026!", admin.hashed_password))
            self.assertFalse(admin.must_change_password)
            db.close()
        finally:
            if old_email_env is not None:
                os.environ["SuperAdminEmail"] = old_email_env
            else:
                os.environ.pop("SuperAdminEmail", None)
            if old_pw_env is not None:
                os.environ["SuperAdminPassword"] = old_pw_env
            else:
                os.environ.pop("SuperAdminPassword", None)
            settings.SUPERADMIN_EMAIL = "test@gmail.com"
            settings.SUPERADMIN_PASSWORD = "1q2w3e4r5t"
            settings.SUPERADMIN_ENV_SET = False

            db = SessionLocal()
            admin = db.query(User).filter(User.role == "superadmin").first()
            if admin:
                from app.auth import get_password_hash
                admin.email = "test@gmail.com"
                admin.hashed_password = get_password_hash("1q2w3e4r5t")
                admin.must_change_password = True
                db.commit()
            db.close()

    def test_08_episode_parser(self):
        from app.parser import parse_episode_info

        # 1. Standard Season folder + episode file
        info1 = parse_episode_info("S01E01.Pilot.1080p.HEVC.mkv", ["Breaking Bad", "Season 01"])
        self.assertIsNotNone(info1)
        self.assertEqual(info1["series_title"], "Breaking Bad")
        self.assertEqual(info1["season_number"], 1)
        self.assertEqual(info1["episode_number"], 1)
        self.assertEqual(info1["codec"], "HEVC")
        self.assertEqual(info1["resolution"], "1080p")

        # 2. Episode in Series folder with title in filename
        info2 = parse_episode_info("Stranger.Things.S04E02.Chapter.Two.mp4", ["Stranger Things"])
        self.assertIsNotNone(info2)
        self.assertEqual(info2["series_title"], "Stranger Things")
        self.assertEqual(info2["season_number"], 4)
        self.assertEqual(info2["episode_number"], 2)

        # 3. 1x05 pattern
        info3 = parse_episode_info("Dark.2x05.720p.mkv", [])
        self.assertIsNotNone(info3)
        self.assertEqual(info3["series_title"], "Dark")
        self.assertEqual(info3["season_number"], 2)
        self.assertEqual(info3["episode_number"], 5)

        # 4. Standard Movie file must NOT be parsed as an episode
        info4 = parse_episode_info("Interstellar.2014.1080p.mkv", ["Movies"])
        self.assertIsNone(info4)

    def test_09_series_models_and_routes(self):
        from app.models import Series, Episode
        from app.auth import create_access_token

        db = SessionLocal()
        # Clean up any existing test series
        existing = db.query(Series).filter(Series.title == "Test Breaking Bad").first()
        if existing:
            for ep in existing.episodes:
                db.delete(ep)
            db.delete(existing)
            db.commit()

        # Ensure admin can browse without first-time change password redirect
        admin_user = db.query(User).filter(User.role == "superadmin").first()
        if admin_user:
            admin_user.must_change_password = False
            db.commit()

        # Create test series
        series = Series(
            title="Test Breaking Bad",
            overview="A chemistry teacher turned manufacturer.",
            genres="Drama, Crime",
            year=2008,
            rating=9.5,
            poster_path="/static/img/poster_placeholder.png"
        )
        db.add(series)
        db.commit()

        ep1 = Episode(
            series_id=series.id,
            season_number=1,
            episode_number=1,
            title="Pilot",
            overview="Walter White gets diagnosed.",
            file_name="Breaking.Bad.S01E01.Pilot.mkv",
            file_size=1048576000,
            gdrive_file_id="gdrive_fake_test_id_ep1",
            resolution="1080p",
            codec="HEVC"
        )
        ep2 = Episode(
            series_id=series.id,
            season_number=1,
            episode_number=2,
            title="Cat's in the Bag...",
            overview="Walt and Jesse clean up.",
            file_name="Breaking.Bad.S01E02.mkv",
            file_size=1048576000,
            gdrive_file_id="gdrive_fake_test_id_ep2",
            resolution="1080p",
            codec="HEVC"
        )
        db.add_all([ep1, ep2])
        db.commit()

        series_id = series.id
        ep1_id = ep1.id
        ep2_id = ep2.id

        # Verify model relationships
        self.assertEqual(series.seasons, [1])
        self.assertEqual(len(series.episodes), 2)
        self.assertEqual(ep1.series.id, series_id)

        db.close()

        # Login admin client
        admin_client = TestClient(app)
        admin_client.post("/login", data={
            "email": "test@gmail.com",
            "password": "1q2w3e4r5t",
            "next": "/"
        })

        # Test Browse Series page
        series_resp = admin_client.get("/series")
        self.assertEqual(series_resp.status_code, 200)
        self.assertIn(b"TV Shows & Web Series", series_resp.content)
        self.assertIn(b"Test Breaking Bad", series_resp.content)

        # Test Series Detail page
        detail_resp = admin_client.get(f"/series/{series_id}")
        self.assertEqual(detail_resp.status_code, 200)
        self.assertIn(b"Test Breaking Bad", detail_resp.content)
        self.assertIn(b"Pilot", detail_resp.content)
        self.assertTrue(b"Cat&#39;s in the Bag..." in detail_resp.content or b"Cat's in the Bag..." in detail_resp.content)

        # Test Watch Episode Player page
        watch_resp = admin_client.get(f"/watch/episode/{ep1_id}")
        self.assertEqual(watch_resp.status_code, 200)
        self.assertIn(b"movi-player", watch_resp.content)
        self.assertIn(b"Next Ep", watch_resp.content)
        self.assertIn(f"/watch/episode/{ep2_id}".encode(), watch_resp.content)

    def test_10_episode_progress_and_home_rendering(self):
        from app.models import Series, Episode, WatchProgress

        db = SessionLocal()
        series = db.query(Series).filter(Series.title == "Test Breaking Bad").first()
        self.assertIsNotNone(series)
        ep1 = series.episodes[0]
        ep1_id = ep1.id
        db.close()

        admin_client = TestClient(app)
        admin_client.post("/login", data={
            "email": "test@gmail.com",
            "password": "1q2w3e4r5t",
            "next": "/"
        })

        # Report progress
        prog_resp = admin_client.post(f"/api/episodes/{ep1_id}/progress", json={
            "position": 350.0,
            "duration": 3400.0
        })
        self.assertEqual(prog_resp.status_code, 200)
        self.assertEqual(prog_resp.json()["status"], "ok")

        # Verify progress saved in database
        db = SessionLocal()
        admin_user = db.query(User).filter(User.email == "test@gmail.com").first()
        prog = db.query(WatchProgress).filter(
            WatchProgress.user_id == admin_user.id,
            WatchProgress.episode_id == ep1_id
        ).first()
        self.assertIsNotNone(prog)
        self.assertAlmostEqual(prog.position_seconds, 350.0)
        self.assertTrue(prog.is_episode)
        db.close()

        # Verify Home page displays episode in Continue Watching and series in Web Series rail
        home_resp = admin_client.get("/")
        self.assertEqual(home_resp.status_code, 200)
        self.assertIn(b"Continue Watching", home_resp.content)
        self.assertIn(b"Web Series & TV Shows", home_resp.content)
        self.assertIn(b"Test Breaking Bad", home_resp.content)

        # Clean up test series, episodes, and watch progress
        db = SessionLocal()
        s = db.query(Series).filter(Series.title == "Test Breaking Bad").first()
        if s:
            for ep in s.episodes:
                wps = db.query(WatchProgress).filter(WatchProgress.episode_id == ep.id).all()
                for wp in wps:
                    db.delete(wp)
                db.delete(ep)
            db.delete(s)
            db.commit()
        db.close()

    def test_11_streaming_head_and_options_cors(self):
        from app.auth import create_access_token

        admin_client = TestClient(app)
        admin_client.post("/login", data={
            "email": "test@gmail.com",
            "password": "1q2w3e4r5t",
            "next": "/"
        })

        tok = create_access_token({"sub": "test@gmail.com", "role": "superadmin"})

        # 1. Test OPTIONS preflight for movie stream
        options_resp = admin_client.options("/stream/raw/5")
        self.assertEqual(options_resp.status_code, 204)
        self.assertEqual(options_resp.headers.get("access-control-allow-origin"), "*")
        self.assertIn("Range", options_resp.headers.get("access-control-allow-headers", ""))

        # 2. Test HEAD probe for movie stream (used by movi-player WASM demuxer)
        head_resp = admin_client.head(f"/stream/raw/5?token={tok}")
        self.assertEqual(head_resp.status_code, 200)
        self.assertEqual(head_resp.headers.get("accept-ranges"), "bytes")
        self.assertEqual(head_resp.headers.get("access-control-allow-origin"), "*")
        self.assertIn("Content-Range", head_resp.headers.get("access-control-expose-headers", ""))

    def test_12_email_resend_and_port_block_handling(self):
        from unittest.mock import patch, MagicMock
        from app.mailer import send_guest_welcome_email, _dispatch_smtp_email
        from email.mime.multipart import MIMEMultipart

        # 1. Test Errno 101 friendly message
        dummy_msg = MIMEMultipart()
        cfg = {"host": "smtp.gmail.com", "port": 465, "use_ssl": True, "user": "test@gmail.com", "password": "apppassword1234"}
        with patch("smtplib.SMTP_SSL", side_effect=OSError(101, "Network is unreachable")):
            with patch("smtplib.SMTP", side_effect=OSError(101, "Network is unreachable")):
                ok, msg = _dispatch_smtp_email("guest@example.com", dummy_msg, cfg)
                self.assertFalse(ok)
                self.assertIn("Render Free Tier blocks outbound SMTP traffic", msg)
                self.assertIn("Resend API Key", msg)

        # 2. Test Resend HTTPS API dispatch when resend_api_key is provided
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"id": "re_12345"}'

        db = SessionLocal()
        from app.routes.superadmin_routes import set_setting_val
        set_setting_val("resend_api_key", "re_test_key_12345", db)

        with patch("httpx.post", return_value=mock_response) as mock_post:
            ok, msg = send_guest_welcome_email(
                guest_email="testguest@example.com",
                guest_name="Test Guest",
                password="TestPassWord!1",
                login_url="http://localhost:8000/login",
                db=db
            )
            self.assertTrue(ok)
            self.assertIn("Resend HTTPS API", msg)
            self.assertTrue(mock_post.called)
            args, kwargs = mock_post.call_args
            self.assertEqual(args[0], "https://api.resend.com/emails")
            self.assertEqual(kwargs["json"]["to"], ["testguest@example.com"])
            self.assertIn("Bearer re_test_key_12345", kwargs["headers"]["Authorization"])

        # Clean up test setting
        set_setting_val("resend_api_key", "", db)
        db.close()

    def test_13_stream_gdrive_quota_html_detection(self):
        from unittest.mock import patch, MagicMock, AsyncMock
        from app.auth import create_access_token

        admin_client = TestClient(app)
        tok = create_access_token({"sub": "test@gmail.com", "role": "superadmin"})

        # Mock an upstream Google Drive response returning 200 OK with text/html (Quota exceeded)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.aclose = AsyncMock()

        # Mock async send
        async def mock_send(req, stream=True):
            return mock_resp

        with patch("httpx.AsyncClient.send", side_effect=mock_send):
            resp = admin_client.get(f"/stream/raw/5?token={tok}", headers={"Range": "bytes=0-1000"})
            self.assertEqual(resp.status_code, 429)
            self.assertIn("quota exceeded", resp.text.lower())

if __name__ == "__main__":
    unittest.main()

