import unittest
from agents import vnc_sources as S

SLUGS = ["raindrops-on-the-window-amlapwfzyf", "a-retro-car-in-the-rain-nfstov1qtq", "majestic-bald-eagle-watching-fireworks-over-the-grand-canyon", "foggy-forest-0abc1def2g", "mountain-top-trail"]


class Sources(unittest.TestCase):
    def test_enabled_depends_on_secrets_only(self):
        self.assertEqual(S.enabled({}), ["mixkit", "coverr", "wikimedia"])
        self.assertEqual(S.enabled({"PEXELS_API_KEY": "k", "PIXABAY_API_KEY": ""}), ["mixkit", "coverr", "wikimedia", "pexels"])

    def test_slug_words_strips_hash_only_when_hash(self):
        self.assertEqual(S.slug_words("raindrops-on-the-window-amlapwfzyf", True), ["raindrops", "window"])
        self.assertEqual(S.slug_words("a-girl-at-the-fair-000yq2o7r9", True), ["girl", "fair"])
        self.assertEqual(S.slug_words("mountain-top-trail"), ["mountain", "top", "trail"])

    def test_coverr_title_search(self):
        got = [s for s, _ in S.coverr_match(SLUGS, "rain")]
        self.assertEqual(set(got), {"raindrops-on-the-window-amlapwfzyf", "a-retro-car-in-the-rain-nfstov1qtq"})
        self.assertEqual(S.coverr_match(SLUGS, "foggy-forest")[0][0], "foggy-forest-0abc1def2g")

    def test_coverr_resolve_own_id_not_related(self):
        html = 'x cdn.coverr.co/videos/coverr-a-retro-car-in-the-rain-8968/thumbnail y cdn.coverr.co/videos/coverr-raindrops-on-the-window-7102/1080p.mp4 z'
        self.assertEqual(S.coverr_resolve(html, "raindrops-on-the-window-amlapwfzyf"), "coverr-raindrops-on-the-window-7102")
        self.assertIsNone(S.coverr_resolve(html, "foggy-forest-0abc1def2g"))
        self.assertIsNone(S.coverr_resolve("cdn.coverr.co/videos/zz9f3k2/1080p.mp4", "raindrops-on-the-window-amlapwfzyf"))  # id sem formato legado (IA/novo) = recusado

    def test_commons_only_cc0_or_pd_and_hd(self):
        def pg(i, t, w, lic):
            return {"pageid": i, "title": t, "imageinfo": [{"url": "u" + str(i), "width": w, "size": 5, "extmetadata": {"LicenseShortName": {"value": lic}}}]}
        j = {"query": {"pages": {"1": pg(1, "File:Rain in Sonoma.webm", 1920, "CC0"), "2": pg(2, "File:Rain 001.webm", 1920, "CC BY-SA 4.0"), "3": pg(3, "File:Rain (1932).webm", 360, "Public domain"), "4": pg(4, "File:Mist.webm", 3840, "Public domain")}}}
        got = S.commons_entries(j)
        self.assertEqual([e["id"] for e in got], ["commons-1", "commons-4"]); self.assertEqual(got[0]["title"], "rain in sonoma")

    def test_pexels_landscape_only_and_pixabay_excludes_animation(self):
        v = {"videos": [{"id": 7, "width": 1920, "height": 1080, "url": "https://www.pexels.com/video/foggy-lake-7/", "video_files": [{"file_type": "video/mp4", "width": 640, "link": "sd"}, {"file_type": "video/mp4", "width": 1920, "link": "hd"}]},
                        {"id": 8, "width": 1080, "height": 1920, "url": "x-8", "video_files": []}]}
        e = S.pexels_entries(v); self.assertEqual([(x["id"], x["preview"], x["hd"], x["title"]) for x in e], [("7", "sd", "hd", "foggy lake")])
        h = {"hits": [{"id": 1, "type": "film", "tags": "rain, window", "pageURL": "p", "videos": {"tiny": {"url": "t"}, "large": {"url": "l"}}}, {"id": 2, "type": "animation", "videos": {"tiny": {"url": "t"}, "large": {"url": "l"}}}]}
        self.assertEqual([x["id"] for x in S.pixabay_entries(h)], ["1"])
