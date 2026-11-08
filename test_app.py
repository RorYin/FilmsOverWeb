import unittest
from fastapi.testclient import TestClient
from app.main import app
from app.parser import parse_filename
from app.gdrive import extract_folder_id
from app.mailer import generate_secure_password
from app.database import Base, engine, SessionLocal
from app.models import User, DriveFolder, Movie
from app.auth import init_default_users

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

        # 3. Test Cloudflare Mail Worker HTTPS dispatch when cloudflare_mail_worker_url is provided
        mock_cf_resp = MagicMock()
        mock_cf_resp.status_code = 200
        mock_cf_resp.json.return_value = {"success": True, "message": "Email sent"}

        set_setting_val("cloudflare_mail_worker_url", "https://mailer.example.workers.dev", db)
        set_setting_val("cloudflare_mail_worker_secret", "secret_pass_123", db)
        set_setting_val("smtp_user", "sender@gmail.com", db)
        set_setting_val("smtp_password", "apppass1234", db)

        with patch("httpx.post", return_value=mock_cf_resp) as mock_cf_post:
            ok, msg = send_guest_welcome_email(
                guest_email="cf_guest@example.com",
                guest_name="CF Guest",
                password="TestPassWord!1",
                login_url="http://localhost:8000/login",
                db=db
            )
            self.assertTrue(ok)
            self.assertIn("Cloudflare Mail Worker", msg)
            self.assertTrue(mock_cf_post.called)
            args, kwargs = mock_cf_post.call_args
            self.assertEqual(args[0], "https://mailer.example.workers.dev")
            self.assertEqual(kwargs["json"]["to"], "cf_guest@example.com")
            self.assertEqual(kwargs["json"]["smtp_user"], "sender@gmail.com")
            self.assertEqual(kwargs["json"]["smtp_pass"], "apppass1234")
            self.assertEqual(kwargs["json"]["secret"], "secret_pass_123")

        # Clean up test settings
        set_setting_val("cloudflare_mail_worker_url", "", db)
        set_setting_val("cloudflare_mail_worker_secret", "", db)
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

    def test_14_google_credentials_from_env_and_override(self):
        import json
        from app.config import settings
        from app.gdrive import get_google_credentials_info
        from app.routes.superadmin_routes import get_setting_val, set_setting_val

        db = SessionLocal()
        # Clean existing test values in DB to test env fallback
        set_setting_val("google_api_key", "", db)
        set_setting_val("google_service_account_json", "", db)

        sample_sa = json.dumps({"type": "service_account", "project_id": "env-test-project"})

        old_api_key = settings.GOOGLE_API_KEY
        old_sa_json = settings.GOOGLE_SERVICE_ACCOUNT_JSON

        try:
            settings.GOOGLE_API_KEY = "AIzaSyTestEnvKey123"
            settings.GOOGLE_SERVICE_ACCOUNT_JSON = sample_sa

            # 1. Verify get_google_credentials_info loads from settings env fallback when DB is empty
            api_key, sa_info = get_google_credentials_info(db)
            self.assertEqual(api_key, "AIzaSyTestEnvKey123")
            self.assertIsNotNone(sa_info)
            self.assertEqual(sa_info.get("project_id"), "env-test-project")

            # 2. Verify superadmin settings view loads env default
            admin_client = TestClient(app)
            admin_client.post("/login", data={"email": "test@gmail.com", "password": "1q2w3e4r5t", "next": "/"})
            res = admin_client.get("/superadmin/settings")
            self.assertEqual(res.status_code, 200)
            self.assertIn("AIzaSyTestEnvKey123", res.text)
            self.assertIn("env-test-project", res.text)

            # 3. Verify user can override it later in the database
            set_setting_val("google_api_key", "AIzaSyUserOverriddenKey", db)
            api_key2, _ = get_google_credentials_info(db)
            self.assertEqual(api_key2, "AIzaSyUserOverriddenKey")

        finally:
            settings.GOOGLE_API_KEY = old_api_key
            settings.GOOGLE_SERVICE_ACCOUNT_JSON = old_sa_json
            set_setting_val("google_api_key", "", db)
            set_setting_val("google_service_account_json", "", db)
            db.close()

    def test_15_guest_filmsoverweb_login_flow(self):
        """Test default guest user (guest@filmsoverweb.com) login without forced password change."""
        db = SessionLocal()
        init_default_users(db)
        guest_user = db.query(User).filter(User.email == "guest@filmsoverweb.com").first()
        self.assertIsNotNone(guest_user)
        self.assertFalse(guest_user.must_change_password)
        self.assertEqual(guest_user.role, "guest")
        db.close()

        # Verify GET /login does not prefill default credentials in the form
        client = TestClient(app)
        login_get = client.get("/login")
        self.assertEqual(login_get.status_code, 200)
        self.assertNotIn(b'value="guest@filmsoverweb.com"', login_get.content)
        self.assertNotIn(b'value="guest@123"', login_get.content)

        # Login as guest@filmsoverweb.com
        login_resp = client.post("/login", data={
            "email": "guest@filmsoverweb.com",
            "password": "guest@123",
            "next": "/"
        }, follow_redirects=False)
        self.assertEqual(login_resp.status_code, 302)
        # Should redirect directly to '/' and NOT to '/change-password'
        self.assertEqual(login_resp.headers.get("location"), "/")

        # Following to home page should succeed without redirecting to change-password
        home_resp = client.get("/", follow_redirects=False)
        self.assertEqual(home_resp.status_code, 200)

        # Attempting to visit /change-password should redirect away to '/'
        change_page_resp = client.get("/change-password", follow_redirects=False)
        self.assertEqual(change_page_resp.status_code, 302)
        self.assertEqual(change_page_resp.headers.get("location"), "/")

        # Attempting to POST to /change-password should be rejected
        change_post_resp = client.post("/change-password", data={
            "current_password": "guest@123",
            "new_password": "newpass12345",
            "confirm_password": "newpass12345"
        })
        self.assertEqual(change_post_resp.status_code, 400)
        self.assertIn(b"Password cannot be changed for the default guest account", change_post_resp.content)

    def test_16_player_engine_endpoints(self):
        """Test that watch pages render the Playback Engine switcher, native player, and M3U playlists."""
        from app.models import Movie, Series, Episode
        db = SessionLocal()
        movie = db.query(Movie).first()
        if not movie:
            movie = Movie(
                title="Test 10-bit HEVC Movie",
                file_name="Test.Movie.2024.2160p.10bit.HEVC.mkv",
                codec="HEVC",
                resolution="4K UHD",
                gdrive_file_id="test_gdrive_movie_id"
            )
            db.add(movie)
            db.commit()

        episode = db.query(Episode).first()
        if not episode:
            series = db.query(Series).first()
            if not series:
                series = Series(title="Test Player Series")
                db.add(series)
                db.commit()
            episode = Episode(
                series_id=series.id,
                title="Test Player Episode",
                file_name="Test.S01E01.mkv",
                gdrive_file_id="test_gdrive_ep_id"
            )
            db.add(episode)
            db.commit()

        movie_id = movie.id
        episode_id = episode.id
        db.close()

        client = TestClient(app)
        # Login as guest to access watch page
        client.post("/login", data={"email": "guest@filmsoverweb.com", "password": "guest@123", "next": "/"})
        
        # Test movie watch page contains pure WASM movi-player with sw="false", hdr, fastseek and no engine switcher dropdown
        watch_resp = client.get(f"/watch/{movie_id}")
        self.assertEqual(watch_resp.status_code, 200)
        self.assertIn(b'movi-player', watch_resp.content)
        self.assertIn(b'sw="false"', watch_resp.content)
        self.assertIn(b'hdr', watch_resp.content)
        self.assertIn(b'fastseek', watch_resp.content)
        self.assertNotIn(b'id="engine-btn"', watch_resp.content)
        self.assertNotIn(b'id="native-player"', watch_resp.content)

        # Test episode watch page contains pure WASM movi-player with sw="false", hdr, fastseek and no engine switcher dropdown
        watch_ep_resp = client.get(f"/watch/episode/{episode_id}")
        self.assertEqual(watch_ep_resp.status_code, 200)
        self.assertIn(b'movi-player', watch_ep_resp.content)
        self.assertIn(b'sw="false"', watch_ep_resp.content)
        self.assertIn(b'hdr', watch_ep_resp.content)
        self.assertIn(b'fastseek', watch_ep_resp.content)
        self.assertNotIn(b'id="engine-btn"', watch_ep_resp.content)
        self.assertNotIn(b'id="native-player"', watch_ep_resp.content)

        # Test movie M3U playlist endpoint
        m3u_resp = client.get(f"/stream/playlist/{movie_id}.m3u")
        self.assertEqual(m3u_resp.status_code, 200)
        self.assertIn(b"#EXTM3U", m3u_resp.content)
        self.assertIn(f"/stream/{movie_id}?token=".encode(), m3u_resp.content)

        # Test episode M3U playlist endpoint
        ep_m3u_resp = client.get(f"/stream/playlist/episode/{episode_id}.m3u")
        self.assertEqual(ep_m3u_resp.status_code, 200)
        self.assertIn(b"#EXTM3U", ep_m3u_resp.content)
        self.assertIn(f"/stream/episode/raw/{episode_id}?token=".encode(), ep_m3u_resp.content)

    def test_17_sync_folder_deletes_removed_content(self):
        """Test that syncing a folder deletes movies and episodes that were removed from Google Drive."""
        from unittest.mock import patch
        import asyncio
        from app.routes.admin_routes import perform_sync_folder
        from app.models import DriveFolder, Movie, Series, Episode

        db = SessionLocal()
        # Create a dedicated test folder
        test_folder = DriveFolder(
            folder_id="test_sync_delete_folder_id",
            folder_name="Sync Deletion Test Folder"
        )
        db.add(test_folder)
        db.commit()

        # Movie 1 will stay in Drive, Movie 2 will be removed from Drive
        m1 = Movie(
            folder_id=test_folder.id,
            gdrive_file_id="staying_movie_fid",
            file_name="Staying.Movie.2024.mp4",
            title="Staying Movie"
        )
        m2 = Movie(
            folder_id=test_folder.id,
            gdrive_file_id="deleted_movie_fid",
            file_name="Deleted.Movie.2024.mp4",
            title="Deleted Movie"
        )
        db.add_all([m1, m2])

        # Series with 2 episodes: ep1 stays in Drive, ep2 will be removed from Drive
        series = Series(
            folder_id=test_folder.id,
            title="Sync Test Series"
        )
        db.add(series)
        db.commit()

        ep1 = Episode(
            folder_id=test_folder.id,
            series_id=series.id,
            season_number=1,
            episode_number=1,
            gdrive_file_id="staying_ep_fid",
            file_name="Series.S01E01.mp4",
            title="Staying Episode"
        )
        ep2 = Episode(
            folder_id=test_folder.id,
            series_id=series.id,
            season_number=1,
            episode_number=2,
            gdrive_file_id="deleted_ep_fid",
            file_name="Series.S01E02.mp4",
            title="Deleted Episode"
        )
        db.add_all([ep1, ep2])
        db.commit()

        # Mock list_files_in_drive_folder to return only m1 and ep1 (m2 and ep2 removed)
        mock_files = [
            {"id": "staying_movie_fid", "name": "Staying.Movie.2024.mp4"},
            {"id": "staying_ep_fid", "name": "Series.S01E01.mp4", "folder_path": ["Sync Test Series", "Season 1"]}
        ]

        async def run_sync():
            with patch("app.routes.admin_routes.list_files_in_drive_folder", return_value=mock_files):
                await perform_sync_folder(test_folder.id, SessionLocal)

        asyncio.run(run_sync())

        # Verify m1 exists, m2 was deleted
        db = SessionLocal()
        self.assertIsNotNone(db.query(Movie).filter(Movie.gdrive_file_id == "staying_movie_fid").first())
        self.assertIsNone(db.query(Movie).filter(Movie.gdrive_file_id == "deleted_movie_fid").first())

        # Verify ep1 exists, ep2 was deleted, series is still there with 1 episode
        self.assertIsNotNone(db.query(Episode).filter(Episode.gdrive_file_id == "staying_ep_fid").first())
        self.assertIsNone(db.query(Episode).filter(Episode.gdrive_file_id == "deleted_ep_fid").first())
        updated_series = db.query(Series).filter(Series.id == series.id).first()
        self.assertIsNotNone(updated_series)
        self.assertEqual(updated_series.total_episodes, 1)

        # Now simulate a second sync where ep1 is also removed (only m1 remains in folder)
        mock_files_no_eps = [
            {"id": "staying_movie_fid", "name": "Staying.Movie.2024.mp4"}
        ]
        async def run_sync2():
            with patch("app.routes.admin_routes.list_files_in_drive_folder", return_value=mock_files_no_eps):
                await perform_sync_folder(test_folder.id, SessionLocal)

        asyncio.run(run_sync2())

        db = SessionLocal()
        # Verify ep1 is now deleted, and the orphan Series with 0 episodes is also deleted
        self.assertIsNone(db.query(Episode).filter(Episode.gdrive_file_id == "staying_ep_fid").first())
        self.assertIsNone(db.query(Series).filter(Series.id == series.id).first())
        self.assertIsNotNone(db.query(Movie).filter(Movie.gdrive_file_id == "staying_movie_fid").first())

        # Clean up test objects
        db.delete(m1)
        db.delete(test_folder)
        db.commit()
        db.close()

    def test_18_superadmin_tv_codes_and_24h_tv_login(self):
        """Test SuperAdmin 5-digit TV code generation and 24-hour expiration on /tv-login."""
        from app.models import TvLoginCode, User
        from app.auth import decode_access_token, COOKIE_NAME

        # 1. Test GET /tv-login renders the TV PIN entry screen
        unauthed_client = TestClient(app)
        get_resp = unauthed_client.get("/tv-login")
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn(b"tv-code-input", get_resp.content)
        self.assertIn(b"tv-code-form", get_resp.content)
        self.assertIn(b"24 hours", get_resp.content)

        # 2. Test Guest cannot access SuperAdmin TV code generator
        guest_client = TestClient(app)
        guest_client.post("/login", data={"email": "guest@filmsoverweb.com", "password": "guest@123", "next": "/"})
        guest_gen_resp = guest_client.post("/superadmin/tv-codes/generate", follow_redirects=False)
        self.assertEqual(guest_gen_resp.status_code, 403)

        # 3. SuperAdmin logs in and generates a 5-digit TV code
        admin_client = TestClient(app)
        admin_client.post("/login", data={"email": "test@gmail.com", "password": "1q2w3e4r5t", "next": "/"})
        gen_resp = admin_client.post("/superadmin/tv-codes/generate", follow_redirects=False)
        self.assertEqual(gen_resp.status_code, 302)
        location = gen_resp.headers.get("location", "")
        self.assertIn("/superadmin/tv-codes?created=", location)
        created_code = location.split("created=")[-1]
        self.assertEqual(len(created_code), 5)
        self.assertTrue(created_code.isdigit())

        # Verify code exists in DB and is unused
        db = SessionLocal()
        tv_code_obj = db.query(TvLoginCode).filter(TvLoginCode.code == created_code).first()
        self.assertIsNotNone(tv_code_obj)
        self.assertFalse(tv_code_obj.is_used)
        code_id = tv_code_obj.id
        db.close()

        # 4. Test submitting invalid code returns 400
        tv_client = TestClient(app)
        inv_resp = tv_client.post("/tv-login", data={"code": "00000"})
        self.assertEqual(inv_resp.status_code, 400)
        self.assertIn(b"Invalid or expired TV code", inv_resp.content)

        # 5. Test submitting the valid 5-digit code
        valid_resp = tv_client.post("/tv-login", data={"code": created_code}, follow_redirects=False)
        self.assertEqual(valid_resp.status_code, 302)
        self.assertEqual(valid_resp.headers.get("location"), "/")

        # Verify auth cookie is set with exactly 24-hour expiration (86400 seconds)
        cookie_header = valid_resp.headers.get("set-cookie", "")
        self.assertIn(COOKIE_NAME, cookie_header)
        self.assertIn("Max-Age=86400", cookie_header)

        # Verify token payload has 24h expiration
        token_str = valid_resp.cookies.get(COOKIE_NAME)
        payload = decode_access_token(token_str)
        self.assertIsNotNone(payload)
        self.assertEqual(payload.get("sub"), "guest@filmsoverweb.com")
        token_lifetime = payload.get("exp") - payload.get("iat", payload.get("exp") - 86400)
        self.assertAlmostEqual(token_lifetime, 86400, delta=120)

        # 6. Verify code is marked as used in DB
        db = SessionLocal()
        used_code_obj = db.query(TvLoginCode).filter(TvLoginCode.code == created_code).first()
        self.assertTrue(used_code_obj.is_used)
        self.assertIsNotNone(used_code_obj.used_at)
        db.close()

        # 7. Test that reusing the same code now fails
        reused_client = TestClient(app)
        reuse_resp = reused_client.post("/tv-login", data={"code": created_code})
        self.assertEqual(reuse_resp.status_code, 400)
        self.assertIn(b"Invalid or expired TV code", reuse_resp.content)

        # 8. Test that active logged-in TV client accessing /tv-login is redirected to /
        already_authed_resp = tv_client.get("/tv-login", follow_redirects=False)
        self.assertEqual(already_authed_resp.status_code, 302)
        self.assertEqual(already_authed_resp.headers.get("location"), "/")

        # 9. SuperAdmin deletes the test code
        del_resp = admin_client.post(f"/superadmin/tv-codes/{code_id}/delete", follow_redirects=False)
        self.assertEqual(del_resp.status_code, 302)
        db = SessionLocal()
        self.assertIsNone(db.query(TvLoginCode).filter(TvLoginCode.id == code_id).first())
        db.close()

    def test_19_superadmin_movie_share_and_48h_pin_security(self):
        """
        Test SuperAdmin-only movie share PIN generation, public view-only details,
        4-digit PIN verification, immediate DB deletion upon verification, single-use enforcement,
        48-hour unlocked streaming cookie, and guest access containment.
        """
        from app.models import MovieSharePin, Movie, User
        from app.auth import decode_access_token, COOKIE_NAME
        from datetime import datetime, timezone, timedelta

        db = SessionLocal()
        for p in db.query(MovieSharePin).all():
            db.delete(p)
        db.commit()
        movie = db.query(Movie).first()
        self.assertIsNotNone(movie, "At least one movie must exist in DB for share testing")
        movie_id = movie.id
        movie_title = movie.title
        admin = db.query(User).filter(User.role == "superadmin").first()
        if admin:
            admin.must_change_password = False
            db.commit()
        db.close()

        # 1. Unauthenticated or non-superadmin cannot generate share links
        anon_client = TestClient(app)
        anon_gen = anon_client.post(f"/api/superadmin/movies/{movie_id}/share", follow_redirects=False)
        self.assertEqual(anon_gen.status_code, 307)
        self.assertIn("/login", anon_gen.headers.get("location", ""))

        guest_client = TestClient(app)
        guest_client.post("/login", data={"email": "guest@filmsoverweb.com", "password": "guest@123", "next": "/"})
        guest_gen = guest_client.post(f"/api/superadmin/movies/{movie_id}/share", follow_redirects=False)
        self.assertEqual(guest_gen.status_code, 403)

        # 2. SuperAdmin generates 48h share link & PIN
        admin_client = TestClient(app)
        admin_client.post("/login", data={"email": "test@gmail.com", "password": "1q2w3e4r5t", "next": "/"})
        gen_resp = admin_client.post(f"/api/superadmin/movies/{movie_id}/share")
        self.assertEqual(gen_resp.status_code, 200)
        data = gen_resp.json()
        self.assertTrue(data.get("success"))
        token = data.get("share_token")
        pin = data.get("pin_code")
        self.assertIsNotNone(token)
        self.assertEqual(len(pin), 4)
        self.assertTrue(pin.isdigit())

        # Verify entry exists in DB
        db = SessionLocal()
        pin_obj = db.query(MovieSharePin).filter(MovieSharePin.share_token == token, MovieSharePin.pin_code == pin).first()
        self.assertIsNotNone(pin_obj)
        self.assertEqual(pin_obj.pin_code, pin)
        self.assertEqual(pin_obj.movie_id, movie_id)
        db.close()

        # 3. Public user opens GET /share/{token} without being logged in
        viewer_client = TestClient(app)
        share_page = viewer_client.get(f"/share/{token}")
        self.assertEqual(share_page.status_code, 200)
        self.assertIn(movie_title.encode("utf-8"), share_page.content)
        self.assertIn(b"Enter 4-Digit PIN", share_page.content)
        self.assertIn(b"Private Shared Screening", share_page.content)
        # Should not show direct watch button when locked
        self.assertNotIn(b"Watch Now (Unlocked)", share_page.content)

        # 4. Viewer tries submitting an incorrect PIN -> 400 error
        wrong_pin = "0000" if pin != "0000" else "1111"
        wrong_pin_resp = viewer_client.post(f"/api/share/{token}/verify", json={"pin": wrong_pin})
        self.assertEqual(wrong_pin_resp.status_code, 400)
        wrong_data = wrong_pin_resp.json()
        self.assertFalse(wrong_data.get("success"))
        self.assertIn("Incorrect 4-digit PIN", wrong_data.get("detail", ""))

        # Verify PIN still in DB
        db = SessionLocal()
        self.assertIsNotNone(db.query(MovieSharePin).filter(MovieSharePin.share_token == token).first())
        db.close()

        # 5. Viewer enters the correct PIN -> Success!
        verify_resp = viewer_client.post(f"/api/share/{token}/verify", json={"pin": pin})
        self.assertEqual(verify_resp.status_code, 200)
        verify_data = verify_resp.json()
        self.assertTrue(verify_data.get("success"))
        self.assertIn("watch_url", verify_data)
        jwt_token = verify_data.get("token")
        self.assertIsNotNone(jwt_token)

        # Verify 48h cookie was set
        cookie_header = verify_resp.headers.get("set-cookie", "")
        self.assertIn(f"fow_share_{token}", cookie_header)
        self.assertIn(f"fow_share_movie_{movie_id}", cookie_header)
        self.assertIn("Max-Age=172800", cookie_header)  # 48 hours = 172800 seconds

        # 6. CRUCIAL: Verify that the PIN is immediately DELETED from the database
        db = SessionLocal()
        deleted_pin_obj = db.query(MovieSharePin).filter(MovieSharePin.share_token == token).first()
        self.assertIsNone(deleted_pin_obj, "The PIN must be deleted from DB upon first verification")
        db.close()

        # 7. Another browser / device attempts to use the same PIN or link -> Fails!
        second_device = TestClient(app)
        second_verify = second_device.post(f"/api/share/{token}/verify", json={"pin": pin})
        self.assertEqual(second_verify.status_code, 400)
        self.assertIn("expired or has already been redeemed", second_verify.json().get("detail", ""))

        second_page = second_device.get(f"/share/{token}")
        self.assertEqual(second_page.status_code, 404)
        self.assertIn(b"Share Link Expired", second_page.content)

        # 8. Original viewer's browser now visits GET /share/{token} -> Unlocked!
        unlocked_page = viewer_client.get(f"/share/{token}")
        self.assertEqual(unlocked_page.status_code, 200)
        self.assertIn(b"PIN Verified", unlocked_page.content)
        self.assertIn(b"Unlocked", unlocked_page.content)

        # 9. Original viewer can access /watch/{movie_id} and stream playback
        watch_resp = viewer_client.get(f"/watch/{movie_id}")
        self.assertEqual(watch_resp.status_code, 200)
        self.assertIn(movie_title.encode("utf-8"), watch_resp.content)
        self.assertIn(b"movi-player", watch_resp.content)

        # 10. Access Restriction Check: Viewer CANNOT access other movies or library pages
        movies_resp = viewer_client.get("/movies", follow_redirects=False)
        self.assertIn(movies_resp.status_code, [307, 403])

        series_resp = viewer_client.get("/series", follow_redirects=False)
        self.assertIn(series_resp.status_code, [307, 403])

        admin_resp = viewer_client.get("/admin/folders", follow_redirects=False)
        self.assertIn(admin_resp.status_code, [307, 403])

        # Viewer CANNOT watch any other movie
        db = SessionLocal()
        other_movie = db.query(Movie).filter(Movie.id != movie_id).first()
        db.close()
        if other_movie:
            other_watch = viewer_client.get(f"/watch/{other_movie.id}", follow_redirects=False)
            self.assertIn(other_watch.status_code, [307, 403])

        # 11. Test 1-Click Embedded PIN Link and Active Share Links Page:
        # Generate another share link with embedded PIN
        gen_resp2 = admin_client.post(f"/api/superadmin/movies/{movie_id}/share")
        data2 = gen_resp2.json()
        token2 = data2.get("share_token")
        pin2 = data2.get("pin_code")
        share_url2 = data2.get("share_url")
        self.assertIn(f"?pin={pin2}", share_url2)

        # 12. SuperAdmin checks active share links on /superadmin/share-links
        # Non-superadmin cannot access
        non_admin_resp = guest_client.get("/superadmin/share-links", follow_redirects=False)
        self.assertEqual(non_admin_resp.status_code, 403)

        # SuperAdmin visits /superadmin/share-links
        admin_links_page = admin_client.get("/superadmin/share-links")
        self.assertEqual(admin_links_page.status_code, 200)
        self.assertIn(movie_title.encode("utf-8"), admin_links_page.content)
        self.assertIn(pin2.encode("utf-8"), admin_links_page.content)
        self.assertIn(token2.encode("utf-8"), admin_links_page.content)

        # 13. Direct 1-Click Hit by Recipient: opens /share/{token2}?pin={pin2}
        direct_viewer = TestClient(app)
        direct_hit = direct_viewer.get(f"/share/{token2}?pin={pin2}")
        self.assertEqual(direct_hit.status_code, 200)
        self.assertIn(b"Unlocked", direct_hit.content)
        self.assertIn(b"PIN Verified", direct_hit.content)

        # Verify 48h cookies were set on this direct-hit browser
        direct_cookies = direct_hit.headers.get("set-cookie", "")
        self.assertIn(f"fow_share_{token2}", direct_cookies)
        self.assertIn(f"fow_share_movie_{movie_id}", direct_cookies)

        # Verify PIN was immediately DELETED from DB on first hit
        db = SessionLocal()
        self.assertIsNone(db.query(MovieSharePin).filter(MovieSharePin.share_token == token2).first())
        db.close()

        # Second device attempting to open the same 1-click URL gets expired error
        other_user_resp = anon_client.get(f"/share/{token2}?pin={pin2}")
        self.assertEqual(other_user_resp.status_code, 404)
        self.assertIn(b"Share Link Expired", other_user_resp.content)

        # 14. SuperAdmin Manual Deletion of an Active Unused Link
        gen_resp3 = admin_client.post(f"/api/superadmin/movies/{movie_id}/share")
        token3 = gen_resp3.json().get("share_token")
        db = SessionLocal()
        pin3_obj = db.query(MovieSharePin).filter(MovieSharePin.share_token == token3).first()
        self.assertIsNotNone(pin3_obj)
        link3_id = pin3_obj.id
        db.close()

        # SuperAdmin deletes link manually
        del_link_resp = admin_client.post(f"/superadmin/share-links/{link3_id}/delete", follow_redirects=False)
        self.assertEqual(del_link_resp.status_code, 302)
        self.assertIn("/superadmin/share-links?deleted=1", del_link_resp.headers.get("location", ""))

        # Verify link is deleted from DB
        db = SessionLocal()
        self.assertIsNone(db.query(MovieSharePin).filter(MovieSharePin.id == link3_id).first())
        db.close()

        # 15. Resilience against Render redeployment ID reassignment:
        # Superadmin generates a share link using ONLY gdrive_file_id in the URL
        gen_resp4 = admin_client.post(f"/api/superadmin/movies/{movie_id}/share")
        self.assertEqual(gen_resp4.status_code, 200)
        data4 = gen_resp4.json()
        token4 = data4.get("share_token")
        pin4 = data4.get("pin_code")
        share_url4 = data4.get("share_url")
        self.assertIn(f"?pin={pin4}", share_url4)
        self.assertNotIn("&file=", share_url4)
        self.assertIn(movie.gdrive_file_id, share_url4)

        # Recipient unlocks access prior to redeployment (receives cookie with pre-redeploy ID)
        redeploy_client = TestClient(app)
        redeploy_hit = redeploy_client.get(share_url4)
        self.assertEqual(redeploy_hit.status_code, 200)
        self.assertIn(b"Unlocked", redeploy_hit.content)

        # Simulate Render redeploying: The database re-indexes Google Drive files in a different order.
        # Movie ID shifts from movie_id to 9999.
        db = SessionLocal()
        m_reindex = db.query(Movie).filter(Movie.id == movie_id).first()
        old_id = m_reindex.id
        m_reindex.id = 9999
        db.commit()
        db.close()

        try:
            # Check that accessing player with gdrive_file_id works directly without caring about DB ID changes
            player_page_gid = redeploy_client.get(f"/watch/{movie.gdrive_file_id}")
            self.assertEqual(player_page_gid.status_code, 200)
            self.assertIn(b"movi-player", player_page_gid.content)

            # Check that accessing old bookmarked watch URL /watch/{old_id} redirects to the current movie
            redir_watch = redeploy_client.get(f"/watch/{old_id}", follow_redirects=False)
            self.assertEqual(redir_watch.status_code, 302)
            redir_loc = redir_watch.headers.get("location", "")
            self.assertTrue(f"/watch/{movie.gdrive_file_id}" in redir_loc or "/watch/9999" in redir_loc)

            # Client can access player for the new re-indexed movie ID 9999
            player_page = redeploy_client.get("/watch/9999")
            self.assertEqual(player_page.status_code, 200)
            self.assertIn(b"movi-player", player_page.content)

            # Client is still strictly forbidden from accessing any other movie ID (e.g. 1234)
            unauth_watch = redeploy_client.get("/watch/1234", follow_redirects=False)
            self.assertIn(unauth_watch.status_code, [307, 403, 404])

            # Also test: A link was generated BEFORE redeployment (stored movie_id=old_id),
            # but redeemed by a recipient AFTER redeployment (movie is now id=9999).
            gen_resp4_post = admin_client.post(f"/api/superadmin/movies/9999/share")
            data4_post = gen_resp4_post.json()
            db = SessionLocal()
            pin_post = db.query(MovieSharePin).filter(MovieSharePin.share_token == data4_post["share_token"]).first()
            pin_post.movie_id = old_id
            db.commit()
            db.close()

            post_redeploy_client = TestClient(app)
            post_resp = post_redeploy_client.get(data4_post["share_url"])
            self.assertEqual(post_resp.status_code, 200)
            self.assertIn(b"Unlocked", post_resp.content)
            post_player = post_redeploy_client.get(f"/watch/{movie.gdrive_file_id}")
            self.assertEqual(post_player.status_code, 200)
            self.assertIn(b"movi-player", post_player.content)
        finally:
            # Restore movie id in DB
            db = SessionLocal()
            m_restore = db.query(Movie).filter(Movie.id == 9999).first()
            if m_restore:
                m_restore.id = old_id
                db.commit()
            db.close()

        # 16. Source Movie Deleted from Google Drive:
        # Create a share link for a movie that is subsequently deleted from Drive
        gen_resp5 = admin_client.post(f"/api/superadmin/movies/{movie_id}/share")
        token5 = gen_resp5.json().get("share_token")
        pin5 = gen_resp5.json().get("pin_code")

        # Simulate movie deleted from Google Drive by temporarily setting MovieSharePin gdrive_file_id & file_name to non-existent
        db = SessionLocal()
        pin5_obj = db.query(MovieSharePin).filter(MovieSharePin.share_token == token5).first()
        pin5_obj.gdrive_file_id = "non_existent_gdrive_id_999999"
        pin5_obj.share_token = "non_existent_gdrive_id_999999"
        pin5_obj.file_name = "DeletedMovie.2024.1080p.mkv"
        pin5_obj.movie_id = 999999
        db.commit()
        db.close()

        # In superadmin/share-links, it should show 'Deleted from Drive' badge
        admin_links_deleted = admin_client.get("/superadmin/share-links")
        self.assertEqual(admin_links_deleted.status_code, 200)
        self.assertIn(b"Deleted from Drive", admin_links_deleted.content)
        self.assertIn(b"DeletedMovie.2024.1080p.mkv", admin_links_deleted.content)

        # A recipient trying to open GET /share/{deleted_id} sees cinema-themed "Source Movie Not Found" error
        missing_viewer = TestClient(app)
        missing_resp = missing_viewer.get("/share/non_existent_gdrive_id_999999")
        self.assertEqual(missing_resp.status_code, 404)
        self.assertIn(b"Source Movie Not Found", missing_resp.content)
        self.assertIn(b"deleted or removed from Google Drive", missing_resp.content)
        self.assertIn(b"DeletedMovie.2024.1080p.mkv", missing_resp.content)

        # Clean up pin5 from DB
        db = SessionLocal()
        p5 = db.query(MovieSharePin).filter(MovieSharePin.share_token == "non_existent_gdrive_id_999999").first()
        if p5:
            db.delete(p5)
            db.commit()
        db.close()

        # 17. WhatsApp / Social Crawler Open Graph Image Indexing and PIN Protection:
        # Generate a share link with PIN
        gen_resp6 = admin_client.post(f"/api/superadmin/movies/{movie_id}/share")
        data6 = gen_resp6.json()
        share_url6 = data6.get("share_url")
        token6 = data6.get("share_token")
        pin6 = data6.get("pin_code")

        # Simulate WhatsApp bot/crawler scraping the URL for link preview
        whatsapp_client = TestClient(app)
        wa_headers = {
            "User-Agent": "WhatsApp/2.21.12.21 i",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        wa_resp = whatsapp_client.get(share_url6, headers=wa_headers)
        self.assertEqual(wa_resp.status_code, 200)

        # Check Open Graph tags and image for WhatsApp indexing
        self.assertIn(b'property="og:image"', wa_resp.content)
        self.assertIn(b'property="og:title"', wa_resp.content)
        self.assertIn(b'property="og:description"', wa_resp.content)
        self.assertIn(b'property="og:type" content="video.movie"', wa_resp.content)
        self.assertIn(b'name="twitter:image"', wa_resp.content)
        self.assertIn(movie_title.encode("utf-8"), wa_resp.content)

        # CRITICAL: Verify that the WhatsApp scraper did NOT consume or delete the PIN!
        db = SessionLocal()
        wa_pin_obj = db.query(MovieSharePin).filter(MovieSharePin.share_token == token6, MovieSharePin.pin_code == pin6).first()
        self.assertIsNotNone(wa_pin_obj, "WhatsApp scraper must NOT consume or delete the PIN from the database")
        db.close()

        # Now real human recipient clicks the link in Chrome/Safari:
        human_client = TestClient(app)
        human_headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        }
        human_resp = human_client.get(share_url6, headers=human_headers)
        self.assertEqual(human_resp.status_code, 200)
        self.assertIn(b"Unlocked", human_resp.content)

        # The PIN is now consumed and deleted from the database!
        db = SessionLocal()
        deleted_wa_pin = db.query(MovieSharePin).filter(MovieSharePin.share_token == token6).first()
        self.assertIsNone(deleted_wa_pin, "Human first click must consume and delete the PIN from the DB")
        db.close()

    def test_20_default_playable_lowest_source(self):
        """
        Verify that when a movie has multiple quality sources in Google Drive:
        1. By default hitting play selects the lowest resolution/size source.
        2. Explicitly selecting another quality (e.g. 4K) plays that selected quality.
        """
        db = SessionLocal()
        # Clean up any existing test movies with this tmdb_id
        for m in db.query(Movie).filter(Movie.tmdb_id == 888777).all():
            db.delete(m)
        db.commit()

        # Create 3 quality versions of the same movie
        m_4k = Movie(
            title="Multi Source Test Film",
            year=2024,
            tmdb_id=888777,
            resolution="4K UHD",
            file_size=15 * 1024 * 1024 * 1024,
            gdrive_file_id="gdrive_4k_test_fid",
            file_name="Multi.Source.Test.Film.2024.2160p.4K.mkv",
            codec="HEVC"
        )
        m_1080 = Movie(
            title="Multi Source Test Film",
            year=2024,
            tmdb_id=888777,
            resolution="1080p",
            file_size=4 * 1024 * 1024 * 1024,
            gdrive_file_id="gdrive_1080p_test_fid",
            file_name="Multi.Source.Test.Film.2024.1080p.mkv",
            codec="HEVC"
        )
        m_720 = Movie(
            title="Multi Source Test Film",
            year=2024,
            tmdb_id=888777,
            resolution="720p",
            file_size=1 * 1024 * 1024 * 1024,
            gdrive_file_id="gdrive_720p_test_fid",
            file_name="Multi.Source.Test.Film.2024.720p.mkv",
            codec="H.264"
        )
        db.add_all([m_4k, m_1080, m_720])
        db.commit()
        db.refresh(m_4k)
        db.refresh(m_1080)
        db.refresh(m_720)
        m_4k_id = m_4k.id
        m_720_id = m_720.id
        db.close()

        # Log in as admin
        admin_client = TestClient(app)
        admin_client.post("/login", data={"email": "test@gmail.com", "password": "1q2w3e4r5t", "next": "/"})

        # 1. Check movie details page
        detail_resp = admin_client.get(f"/movie/{m_4k_id}")
        self.assertEqual(detail_resp.status_code, 200)

        # Primary play button should point to lowest resolution source (720p)
        self.assertIn(f'/watch/{m_720_id}'.encode(), detail_resp.content)

        # Available qualities list should offer explicit selection links
        self.assertIn(f'/watch/{m_4k_id}?select=explicit'.encode(), detail_resp.content)

        # 2. Hitting /watch/{m_4k_id} WITHOUT ?select=explicit should default to the lowest source (720p)
        watch_default = admin_client.get(f"/watch/{m_4k_id}")
        self.assertEqual(watch_default.status_code, 200)
        self.assertIn(b"gdrive_720p_test_fid", watch_default.content)

        # 3. Hitting /watch/{m_4k_id} WITH ?select=explicit should play the selected 4K source
        watch_explicit = admin_client.get(f"/watch/{m_4k_id}?select=explicit")
        self.assertEqual(watch_explicit.status_code, 200)
        self.assertIn(b"gdrive_4k_test_fid", watch_explicit.content)

        # Clean up
        db = SessionLocal()
        for m in db.query(Movie).filter(Movie.tmdb_id == 888777).all():
            db.delete(m)
        db.commit()
        db.close()

if __name__ == "__main__":
    unittest.main()


