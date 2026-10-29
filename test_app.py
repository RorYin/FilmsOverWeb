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

if __name__ == "__main__":
    unittest.main()


