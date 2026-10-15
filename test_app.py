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

    def test_04_auth_and_login(self):
        # Attempt login with default SuperAdmin
        resp = self.client.post("/login", data={
            "email": "drmnbot@gmail.com",
            "password": "SuperAdmin@2026",
            "next": "/"
        }, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("fow_token", resp.cookies)

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
                is_active=True
            )
            db.add(guest)
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

    def test_06_superadmin_access(self):
        admin_client = TestClient(app)
        admin_client.post("/login", data={
            "email": "drmnbot@gmail.com",
            "password": "SuperAdmin@2026",
            "next": "/"
        })

        # Superadmin can view settings
        settings_resp = admin_client.get("/superadmin/settings")
        self.assertEqual(settings_resp.status_code, 200)

        # Superadmin can view admins
        admins_resp = admin_client.get("/superadmin/admins")
        self.assertEqual(admins_resp.status_code, 200)

        # Superadmin can view folders
        folders_resp = admin_client.get("/admin/folders")
        self.assertEqual(folders_resp.status_code, 200)

        # Superadmin can view guests
        guests_resp = admin_client.get("/admin/guests")
        self.assertEqual(guests_resp.status_code, 200)

if __name__ == "__main__":
    unittest.main()
