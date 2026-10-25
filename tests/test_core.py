"""
Offline tests for MediaCleanup: no config, no network, no media files, standard library only.

Run:  python -m unittest discover -s tests -v

They cover the pieces where a quiet mistake would be expensive: the guards that keep secrets out
of logs, the checks around downloads and self-update, how a subtitle is scored and verified, and
a scan that fails if a stray control character ever lands in the source (a literal backspace once
replaced a regex word boundary in three patterns without anything failing).
"""
import hashlib
import importlib.util
import io
import logging
import re
import subprocess
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("mediacleanup", ROOT / "MediaCleanup.py")
mc = importlib.util.module_from_spec(_spec)
sys.modules["mediacleanup"] = mc
_spec.loader.exec_module(mc)


class SourceIntegrity(unittest.TestCase):
    TEXT = (".py", ".md", ".toml", ".ps1", ".yml", ".yaml", ".svg", ".txt", ".json", ".gitignore")
    SKIP_DIRS = {".git", "runtimes", "logs", "backup", "__pycache__", "linkedin", "scratch"}

    def files(self):
        for p in ROOT.rglob("*"):
            if (p.is_file() and not (set(p.relative_to(ROOT).parts) & self.SKIP_DIRS)
                    and p.suffix in self.TEXT and p.name not in ("PROMPT.md", "MediaCleanup.toml")):
                yield p

    def test_no_control_characters(self):
        bad = {}
        for p in self.files():
            found = sorted({b for b in p.read_bytes() if b < 32 and b not in (9, 10, 13)})
            if found:
                bad[str(p.relative_to(ROOT))] = found
        self.assertEqual(bad, {}, "stray control characters (0x08 is a backspace where a regex word boundary was meant)")

    def test_source_compiles_and_has_no_dangerous_constructs(self):
        text = (ROOT / "MediaCleanup.py").read_text(encoding="utf-8")
        compile(text, "MediaCleanup.py", "exec")
        for pattern in ("shell=True", "os.system(", "eval(", "exec(", "pickle", "yaml.load",
                        "_create_unverified_context", "verify=False"):
            self.assertNotIn(pattern, text, pattern)

    def test_no_secrets_or_real_ids_in_tracked_text(self):
        key_value = re.compile(r"""(?i)(tmdb_api_key|fanarttv_api_key|omdb_api_key|api_key|password|username)\s*=\s*["'][^"'\s]{4,}["']""")
        for p in self.files():
            text = p.read_text(encoding="utf-8", errors="replace")
            if p.parent.name != "tests":      # the tests hold deliberately fake credentials to test the redactor
                self.assertIsNone(key_value.search(text), f"a key assignment with a value in {p.name}")
            self.assertIsNone(re.search(r"(ghp|gho|ghu|ghs)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}", text), p.name)
            self.assertNotIn("-----BEGIN " + "PRIVATE KEY-----", text)    # (built in two pieces so this file does not match itself)

    def test_private_files_are_not_tracked(self):
        try:
            tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout")
        self.assertNotIn("MediaCleanup.toml", tracked)
        self.assertFalse([f for f in tracked if f.startswith(("logs/", "backup/", "linkedin/"))])
        self.assertFalse([f for f in tracked if f.endswith(".log")])

    def test_version_matches_changelog_and_readme(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        newest = mc.parse_changelog_sections(changelog)[0]
        self.assertEqual(".".join(map(str, newest[0])), mc.__version__)
        self.assertIn(f"version-{mc.__version__}-", (ROOT / "README.md").read_text(encoding="utf-8"))


class Redaction(unittest.TestCase):
    KEY = "0123456789abcdef0123456789abcdef"

    def setUp(self):
        self._cfg = getattr(mc, "CFG", None)
        mc.CFG = types.SimpleNamespace(TMDB_API_KEY=self.KEY, FANARTTV_API_KEY="", OMDB_API_KEY="a1b2c3d4",
                                       OS_API_KEY="", OS_PASSWORD="hunter22!")

    def tearDown(self):
        mc.CFG = self._cfg

    def test_keys_in_urls(self):
        out = mc.redact_secrets(f"https://api.themoviedb.org/3/x?api_key={self.KEY}&query=film")
        self.assertNotIn(self.KEY, out)
        self.assertIn("api_key=***", out)
        self.assertIn("query=film", out)
        self.assertIn("apikey=***", mc.redact_secrets("https://www.omdbapi.com/?i=tt1&apikey=deadbeef"))

    def test_configured_values_anywhere(self):
        self.assertNotIn(self.KEY, mc.redact_secrets(f"the key {self.KEY} was used"))
        self.assertNotIn("hunter22!", mc.redact_secrets("password is hunter22!"))

    def test_bearer_and_pairs(self):
        self.assertNotIn("abcdefghijklmnop1234", mc.redact_secrets("Authorization: Bearer abcdefghijklmnop1234"))
        self.assertIn("password=***", mc.redact_secrets("login password=abc123 ok"))

    def test_ordinary_text_untouched(self):
        text = "Cleaning tags: 3 tokens=5, passwordless login ok"
        self.assertEqual(mc.redact_secrets(text), text)

    def test_handlers_redact_messages_and_tracebacks(self):
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.addFilter(mc._RedactingFilter())
        log = logging.getLogger("redaction-test")
        log.setLevel(logging.DEBUG)
        log.propagate = False
        log.addHandler(handler)
        try:
            log.debug("HTTP GET failed: %s", f"https://api.themoviedb.org/3/x?api_key={self.KEY}")
            try:
                raise RuntimeError(f"boom https://www.omdbapi.com/?apikey=a1b2c3d4")
            except RuntimeError:
                log.exception("crashed")
        finally:
            log.removeHandler(handler)
        out = buf.getvalue()
        self.assertNotIn(self.KEY, out)
        self.assertNotIn("a1b2c3d4", out)
        self.assertIn("HTTP GET failed", out)
        self.assertIn("Traceback", out)


class SafeDownloads(unittest.TestCase):
    def test_public_https_only(self):
        ok = mc._public_https_url
        self.assertTrue(ok("https://8.8.8.8/x.jpg"))
        for url in ("http://8.8.8.8/x.jpg", "ftp://8.8.8.8/x", "https://localhost/x", "https://127.0.0.1/x",
                    "https://[::1]/x", "https://10.1.2.3/x", "https://192.168.0.10/x", "https://172.16.5.5/x",
                    "https://169.254.169.254/latest/meta-data", "https://0.0.0.0/x", "https://printer.local/x",
                    "https://thing.internal/x", "https://foo.localhost/x", "not a url", "https:///nohost"):
            self.assertFalse(ok(url), url)

    def test_redirects_must_stay_public(self):
        import urllib.error
        import urllib.request
        handler = mc._PublicHttpsRedirects()
        req = urllib.request.Request("https://8.8.8.8/a.jpg")
        for target in ("http://169.254.169.254/latest", "https://192.168.0.1/admin"):
            with self.assertRaises(urllib.error.URLError):
                handler.redirect_request(req, None, 302, "Found", {}, target)
        self.assertIsNotNone(handler.redirect_request(req, None, 302, "Found", {}, "https://1.1.1.1/b.jpg"))

    def test_refuses_to_connect_to_internal_addresses(self):
        self.assertIsNone(mc._http_get_bytes("https://169.254.169.254/latest/meta-data"))
        self.assertIsNone(mc._http_get_bytes("http://8.8.8.8/x.jpg"))

    def test_runtime_download_hosts(self):
        ok = mc._runtime_url_ok
        self.assertTrue(ok("https://mkvtoolnix.download/x") and ok("https://www.gyan.dev/y") and ok("https://pypi.org/z"))
        for url in ("http://mkvtoolnix.download/x", "https://mkvtoolnix.download.evil.example/x",
                    "https://mkvtoolnix.download@evil.example/x", "https://evil.example/mkvtoolnix.download"):
            self.assertFalse(ok(url), url)


class SelfUpdate(unittest.TestCase):
    def test_release_paths(self):
        for bad in ("../x", "/abs", "C:/x", "a/../b", "a\\b", "", "a//b"):
            self.assertFalse(mc._safe_release_path(bad), bad)
        self.assertTrue(mc._safe_release_path("docs/images/a.svg"))
        for protected in ("MediaCleanup.toml", "logs/x", "backup/y", ".git/config"):
            self.assertTrue(mc._is_protected_path(protected), protected)
        self.assertFalse(mc._is_protected_path("runtimes/README.md"))

    def test_git_blob_hash_matches_git(self):
        self.assertEqual(mc.git_blob_sha1(b"hello\n"), "ce013625030ba8dba906f756967f9e9ca394464a")
        self.assertIn(mc.git_blob_sha1(b"a\nb\n"), mc._local_blob_shas(self._file(b"a\r\nb\r\n")))

    def _file(self, data):
        p = Path(tempfile.mkdtemp()) / "f.txt"
        p.write_bytes(data)
        return p

    def test_plan_flags_edits_and_never_touches_protected_files(self):
        sha = mc.git_blob_sha1
        old = {"a.md": (sha(b"1"), "100644"), "gone.md": (sha(b"x"), "100644")}
        new = {"a.md": (sha(b"2"), "100644"), "new.md": (sha(b"n"), "100644")}
        root = Path(tempfile.mkdtemp())
        (root / "a.md").write_bytes(b"MY EDIT")
        (root / "gone.md").write_bytes(b"x")
        plan = mc.build_update_plan(root, old, new)
        self.assertEqual((plan.add, plan.replace, plan.remove), (["new.md"], ["a.md"], ["gone.md"]))
        self.assertEqual(plan.edited, ["a.md"])

    def test_extract_verified_rejects_tampering_and_missing_files(self):
        good = b"print('v2')\n"
        tree = {"MediaCleanup.py": (mc.git_blob_sha1(good), "100644")}

        def archive(content):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("owner-repo-abc/MediaCleanup.py", content)
            return buf.getvalue()

        out = Path(tempfile.mkdtemp())
        self.assertIsNone(mc.extract_verified(archive(good), tree, ["MediaCleanup.py"], out))
        self.assertIn("does not match", mc.extract_verified(archive(b"EVIL"), tree, ["MediaCleanup.py"], Path(tempfile.mkdtemp())))
        self.assertIn("missing", mc.extract_verified(archive(good), {**tree, "x": ("0" * 40, "100644")}, ["x"], Path(tempfile.mkdtemp())))
        self.assertIn("not a valid zip", mc.extract_verified(b"junk", tree, ["MediaCleanup.py"], Path(tempfile.mkdtemp())))

    def test_zip_slip_is_refused(self):
        archive = Path(tempfile.mkdtemp()) / "slip.zip"
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr("../escape.txt", b"bad")
        self.assertIn("outside", mc.extract_archive(archive, Path(tempfile.mkdtemp())))

    def test_versions_and_checksums(self):
        self.assertEqual(mc.parse_version("v1.11.0"), (1, 11, 0))
        self.assertLess(mc.parse_version("1.9.0"), mc.parse_version("1.10.0"))
        self.assertIsNone(mc.parse_version("latest"))
        self.assertEqual(mc._parse_sha256("A" * 64), "a" * 64)
        listing = f"{'b' * 64}  other.exe\n{'c' * 64}  want.7z\n"
        self.assertEqual(mc._parse_sha256(listing, "want.7z"), "c" * 64)
        self.assertIsNone(mc._parse_sha256("<html>404</html>"))


class Subtitles(unittest.TestCase):
    @staticmethod
    def srt(cues, last_end, first_start=5.0, ad_after=False):
        def ts(x):
            return f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(x % 1 * 1000):03d}"
        step = (last_end - first_start) / max(1, cues - 1)
        blocks = [f"{i + 1}\n{ts(first_start + i * step)} --> {ts(first_start + i * step + 2)}\nLine {i + 1}" for i in range(cues)]
        if ad_after:
            blocks.append(f"{cues + 1}\n{ts(last_end + 5)} --> {ts(last_end + 8)}\nDownload more subtitles at www.example-subs.com")
        return ("\n\n".join(blocks) + "\n").encode()

    def test_searches_are_precise_sorted_and_never_by_title(self):
        film = mc.build_subtitle_searches("tt0063350", "ABCDEF0123456789", "EN")
        self.assertEqual(film[0], {"imdb_id": "63350", "languages": "en", "moviehash": "abcdef0123456789"})
        self.assertEqual(film[-1].get("moviehash_match"), "only")
        self.assertEqual(mc.build_subtitle_searches(None, None, "en"), [])      # no title search any more
        tv = mc.build_subtitle_searches("tt0000001", None, "en", is_tv=True, season=2, episode=5)
        self.assertEqual(tv, [{"episode_number": "5", "languages": "en", "parent_imdb_id": "1", "season_number": "2"}])
        self.assertTrue(all("imdb_id" not in p for p in tv))
        self.assertEqual(mc.search_query_string({"query": "a b&c", "languages": "en", "imdb_id": "1"}),
                         "imdb_id=1&languages=en&query=a%20b%26c")

    def test_scoring(self):
        target = mc.SubtitleTarget(name="The Film (2023) - WEBRip.1080p.x265 - [English]", duration_s=5708.0, fps=23.976)

        def attrs(**kw):
            base = dict(release="", fps=0.0, nb_cd=1, download_count=0, ratings=0, hearing_impaired=False, from_trusted=False,
                        machine_translated=False, foreign_parts_only=False, ai_translated=False, moviehash_match=False)
            base.update(kw)
            return base

        score = lambda **kw: mc.score_subtitle_candidate(attrs(**kw), target)[0]
        for excluded in ({"nb_cd": 2}, {"machine_translated": True}, {"foreign_parts_only": True}):
            self.assertIsNone(score(**excluded))
        self.assertGreater(score(moviehash_match=True), score(download_count=25000, from_trusted=True) + 900)
        self.assertGreater(score(release="Film"), score(release="Film (Colorized)", download_count=300))
        self.assertGreater(score(release="Film.2023.WebRip"), score(release="Film.2023.BluRay.X264-GRP"))
        self.assertGreater(score(fps=23.976), score(fps=0.0))
        self.assertGreater(score(fps=0.0), score(fps=25.0))
        self.assertGreater(score(release="Scan 1:35:08"), score(release="Cut 2:10:00"))

    def test_verification_against_the_video_length(self):
        d = 5708.0
        fits, why, text = mc.verify_subtitle_fit(self.srt(900, 5500), d)
        self.assertTrue(fits, why)
        self.assertEqual(text.count("-->"), 900)
        for raw, expected in ((self.srt(900, 7200), "runs to"), (self.srt(900, 2400), "only 42%"),
                              (self.srt(900, 5500, first_start=3000.0), "first line"), (self.srt(6, 5500), "only 6 lines"),
                              (b"not a subtitle", "not a readable")):
            fits, why, _ = mc.verify_subtitle_fit(raw, d)
            self.assertFalse(fits)
            self.assertIn(expected, why)
        fits, why, text = mc.verify_subtitle_fit(self.srt(900, 5660, ad_after=True), d)
        self.assertTrue(fits, why)
        self.assertNotIn("example-subs", text)
        self.assertTrue(mc.verify_subtitle_fit(self.srt(900, 7200), None)[0])    # unknown duration: not checked

    def test_release_signals_and_language_codes(self):
        self.assertEqual(mc.edition_words("Film.REMASTERED.Directors.Cut"), {"remastered", "directors cut"})
        self.assertEqual(mc.edition_words("Film (Open Matte)"), set())           # framing, not a different cut
        self.assertEqual(mc.release_source("Film.2023.WEB-DL"), "web")
        self.assertEqual(mc.release_group("Film.720p.BluRay.X264-AMIABLE"), "amiable")
        self.assertEqual(mc.runtime_hint("Open Matte 1:35:08"), 5708.0)
        self.assertEqual(mc.fmt_hms(5708), "1:35:08")
        for three, two in (("ger", "de"), ("spa", "es"), ("chi", "zh"), ("jpn", "ja"), ("eng", "en")):
            self.assertEqual(mc.subtitle_lang_iso1(three), two)
        self.assertIsNone(mc.subtitle_lang_iso1("und"))


class AdvertDetection(unittest.TestCase):
    def test_web_addresses_and_domains_are_adverts(self):
        for text in ("Download more subtitles at www.example-subs.com", "Visit www.example.com for subtitles",
                     "Get them at example.com now", "Subtitles by SomeSite.net"):
            self.assertTrue(mc._looks_like_advertising(text), text)

    def test_dialogue_is_not(self):
        for text in ("I read it on the internet", "She wore a wig.", "Meet me at the club.", "Is it to-do or not."):
            self.assertFalse(mc._looks_like_advertising(text), text)

    def test_resolution_is_read_from_a_filename(self):
        track = mc.Track(file=None, id=0, type="video", codec_id="", codec="", language="und", name="", default=False, forced=False)
        self.assertEqual(mc.infer_resolution_tag_from_video(track, fallback_filename="Film.2023.1080p.WEB.x264.mkv"), "1080p")


class Naming(unittest.TestCase):
    def test_output_name_template(self):
        name = mc.build_movie_output_name("Film", "2023", "tt0063350", "1080p", "WEB-DL", "x264", [], bracket="Hindi + English")
        self.assertEqual(name, "Film (2023) - tt0063350 - WEB-DL.1080p.x264 - [Hindi + English].mkv")
        self.assertEqual(mc.build_movie_output_name("Film", "2023", None, "1080p", None, "x264", [], bracket="English"),
                         "Film (2023) - WebRip.1080p.x264 - [English].mkv")

    def test_local_names_need_a_usable_title(self):
        self.assertTrue(mc._local_title_usable("Some Film", "2023", need_year=True))
        self.assertFalse(mc._local_title_usable("Some Film", None, need_year=True))
        self.assertFalse(mc._local_title_usable("", "2023", need_year=True))
        self.assertEqual(mc._tidy_title("lord of the films"), "Lord of the Films")
        self.assertEqual(mc._tidy_title("RRR"), "RRR")                           # capitals are information

    def test_title_matching(self):
        self.assertTrue(mc._title_prefix_matches("The Film: A Longer Subtitle", "The Film"))
        self.assertFalse(mc._title_prefix_matches("The Filmmaker", "The Film"))
        self.assertEqual(mc._match_key("A & B"), mc._match_key("A.And.B"))


if __name__ == "__main__":
    unittest.main()
