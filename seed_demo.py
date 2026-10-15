"""
Seeds sample movie records so the user can explore the Netflix/Prime OTT interface immediately.
"""
from app.database import SessionLocal, Base, engine
from app.models import Movie, DriveFolder, User
from app.auth import get_password_hash

def seed_demo_data():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Check if movies already exist
    existing_count = db.query(Movie).count()
    if existing_count > 0:
        print(f"[SEED] Database already has {existing_count} movies. Skipping demo seed.")
        db.close()
        return

    print("[SEED] Seeding demo OTT library with HEVC, AV1, and 4K movies...")

    # Create a demo folder
    folder = DriveFolder(
        folder_id="demo_folder_1a2b3c4d5e",
        folder_name="4K HDR & HEVC Cinema Vault",
        folder_url="https://drive.google.com/drive/folders/demo_folder_1a2b3c4d5e",
        movie_count=4
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)

    demo_movies = [
        {
            "gdrive_file_id": "demo_file_oppenheimer_hevc",
            "folder_id": folder.id,
            "file_name": "Oppenheimer.2023.IMAX.2160p.UHD.HDR.HEVC.Atmos.mkv",
            "file_size": 18456123456,
            "mime_type": "video/mp4",
            "codec": "HEVC",
            "resolution": "4K UHD",
            "tmdb_id": 872585,
            "title": "Oppenheimer",
            "original_title": "Oppenheimer",
            "year": 2023,
            "overview": "The story of American scientist J. Robert Oppenheimer and his role in the development of the atomic bomb during World War II.",
            "tagline": "The world forever changes.",
            "poster_path": "https://image.tmdb.org/t/p/w500/8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg",
            "backdrop_path": "https://image.tmdb.org/t/p/original/rLb2cw69zbTXGIv01DWXxl739hH.jpg",
            "rating": 8.4,
            "vote_count": 8200,
            "duration": 180,
            "genres": "Drama, History, Thriller",
            "cast": "Cillian Murphy, Emily Blunt, Matt Damon, Robert Downey Jr., Florence Pugh",
            "director": "Christopher Nolan",
            "trailer_url": "https://www.youtube.com/watch?v=uYPbbksJxIg"
        },
        {
            "gdrive_file_id": "demo_file_spiderverse_av1",
            "folder_id": folder.id,
            "file_name": "Spider-Man.Across.the.Spider-Verse.2023.1080p.WEBRip.AV1.mp4",
            "file_size": 4256123456,
            "mime_type": "video/mp4",
            "codec": "AV1",
            "resolution": "1080p",
            "tmdb_id": 569094,
            "title": "Spider-Man: Across the Spider-Verse",
            "original_title": "Spider-Man: Across the Spider-Verse",
            "year": 2023,
            "overview": "After reuniting with Gwen Stacy, Brooklyn's full-time, friendly neighborhood Spider-Man is catapulted across the Multiverse, where he encounters the Spider Society, a team of Spider-People charged with protecting the Multiverse's very existence.",
            "tagline": "It's how you wear the mask that matters.",
            "poster_path": "https://image.tmdb.org/t/p/w500/8Vt6mWEReuy4Of61Lnj5Xj704m8.jpg",
            "backdrop_path": "https://image.tmdb.org/t/p/original/4HodYYKEIsGOdinkGi2Ucz6X9i0.jpg",
            "rating": 8.6,
            "vote_count": 6400,
            "duration": 140,
            "genres": "Animation, Action, Adventure, Sci-Fi",
            "cast": "Shameik Moore, Hailee Steinfeld, Brian Tyree Henry, Luna Lauren Velez, Jake Johnson",
            "director": "Joaquim Dos Santos, Kemp Powers, Justin K. Thompson",
            "trailer_url": "https://www.youtube.com/watch?v=cqGjhVJWtEg"
        },
        {
            "gdrive_file_id": "demo_file_dune2_hevc",
            "folder_id": folder.id,
            "file_name": "Dune.Part.Two.2024.2160p.UHD.HDR.HEVC.mkv",
            "file_size": 22123456789,
            "mime_type": "video/mp4",
            "codec": "HEVC",
            "resolution": "4K UHD",
            "tmdb_id": 693134,
            "title": "Dune: Part Two",
            "original_title": "Dune: Part Two",
            "year": 2024,
            "overview": "Follow the mythic journey of Paul Atreides as he unites with Chani and the Fremen while on a path of revenge against the conspirators who destroyed his family.",
            "tagline": "Long live the fighters.",
            "poster_path": "https://image.tmdb.org/t/p/w500/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
            "backdrop_path": "https://image.tmdb.org/t/p/original/xOMo8BRK7PfcJv9JCnx7s5hj0PX.jpg",
            "rating": 8.5,
            "vote_count": 4800,
            "duration": 166,
            "genres": "Sci-Fi, Adventure, Action",
            "cast": "Timothée Chalamet, Zendaya, Rebecca Ferguson, Javier Bardem, Josh Brolin",
            "director": "Denis Villeneuve",
            "trailer_url": "https://www.youtube.com/watch?v=Way9Dexny3w"
        },
        {
            "gdrive_file_id": "demo_file_interstellar_hevc",
            "folder_id": folder.id,
            "file_name": "Interstellar.2014.1080p.BluRay.x265.mp4",
            "file_size": 8500123456,
            "mime_type": "video/mp4",
            "codec": "HEVC",
            "resolution": "1080p",
            "tmdb_id": 157336,
            "title": "Interstellar",
            "original_title": "Interstellar",
            "year": 2014,
            "overview": "The adventures of a group of explorers who make use of a newly discovered wormhole to surpass the limitations on human space travel and conquer the vast distances involved in an interstellar voyage.",
            "tagline": "Mankind was born on Earth. It was never meant to die here.",
            "poster_path": "https://image.tmdb.org/t/p/w500/gEU2QniE6E77NI6lCU6MxlNBvIx.jpg",
            "backdrop_path": "https://image.tmdb.org/t/p/original/xJHokMbljvjADYdit5fK5VQsXEG.jpg",
            "rating": 8.7,
            "vote_count": 34000,
            "duration": 169,
            "genres": "Adventure, Drama, Sci-Fi",
            "cast": "Matthew McConaughey, Anne Hathaway, Jessica Chastain, Michael Caine, Matt Damon",
            "director": "Christopher Nolan",
            "trailer_url": "https://www.youtube.com/watch?v=zSWdZVtXT7E"
        }
    ]

    for m in demo_movies:
        movie_obj = Movie(**m)
        db.add(movie_obj)

    db.commit()
    db.close()
    print("[SEED] Successfully added demo movies to library.")

if __name__ == "__main__":
    seed_demo_data()
