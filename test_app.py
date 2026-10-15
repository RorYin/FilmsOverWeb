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

if __name__ == "__main__":
    unittest.main()
