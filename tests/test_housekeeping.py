"""Space-saving upkeep: old, larger files are converted once and every record pointing at them follows."""
import os
import shutil
import unittest
from unittest import mock

from tests import TEMP_DIR
import database
import housekeeping
import image_engine

try:
    from PIL import Image
except ImportError:
    Image = None


def execute(sql, rows=((),)):
    conn = database.get_db_connection()
    conn.executemany(sql, rows)
    conn.commit()
    conn.close()


@unittest.skipUnless(Image, "needs Pillow")
class Photos(unittest.TestCase):
    def setUp(self):
        # A private static folder: never the real generated photos
        self.static = os.path.join(TEMP_DIR, "static")
        shutil.rmtree(self.static, ignore_errors=True)
        os.makedirs(os.path.join(self.static, "generated"))
        patcher = mock.patch.object(database, "STATIC_DIR", self.static)
        patcher.start()
        self.addCleanup(patcher.stop)
        Image.new("RGB", (64, 36), (200, 160, 20)).save(os.path.join(self.static, "generated", "tweet_w1_1_0.png"))
        execute("DELETE FROM historical_tweets")
        execute("INSERT INTO historical_tweets (week_num, user_handle, display_name, tweet_text, likes, retweets, views, image_path) "
                "VALUES (1, '@a', 'A', 'hi', '1K', '1K', '1K', 'generated/tweet_w1_1_0.png')")

    def test_png_becomes_webp_and_records_follow(self):
        self.assertEqual(housekeeping.convert_photos(), 1)
        self.assertEqual(os.listdir(os.path.join(self.static, "generated")), ["tweet_w1_1_0.webp"])
        conn = database.get_db_connection()
        self.assertEqual(conn.execute("SELECT image_path FROM historical_tweets").fetchone()[0], "generated/tweet_w1_1_0.webp")
        conn.close()
        self.assertEqual(housekeeping.convert_photos(), 0)  # nothing left to do

    def test_new_photos_are_saved_as_webp(self):
        import io
        png = io.BytesIO()
        Image.new("RGB", (64, 36)).save(png, "PNG")
        stem = os.path.join(self.static, "generated", "hero_w2_1")
        self.assertEqual(image_engine.save_photo(png.getvalue(), stem), ".webp")
        self.assertTrue(os.path.exists(stem + ".webp"))


if __name__ == "__main__":
    unittest.main()
