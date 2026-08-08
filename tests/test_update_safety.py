from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from re import compile as re_compile
from subprocess import PIPE, run

import update

ROOT = Path(__file__).parents[1]


def _git(cwd, *args):
    result = run(
        ["git", *args],
        cwd=cwd,
        stdout=PIPE,
        stderr=PIPE,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _repositories(tmp_path):
    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    checkout = tmp_path / "checkout"

    _git(tmp_path, "init", "--bare", str(remote))
    _git(tmp_path, "clone", str(remote), str(seed))
    _git(seed, "checkout", "-b", "main")
    _git(seed, "config", "user.email", "tests@example.invalid")
    _git(seed, "config", "user.name", "Amaterasu tests")
    (seed / "tracked.txt").write_text("initial\n", encoding="utf-8")
    _git(seed, "add", "tracked.txt")
    _git(seed, "commit", "-m", "initial")
    _git(seed, "push", "-u", "origin", "main")
    _git(tmp_path, "clone", "--branch", "main", str(remote), str(checkout))
    return remote, seed, checkout


def _add_upstream_commit(seed, content):
    (seed / "tracked.txt").write_text(content, encoding="utf-8")
    _git(seed, "add", "tracked.txt")
    _git(seed, "commit", "-m", "upstream change")
    _git(seed, "push", "origin", "main")


def test_dirty_working_tree_is_preserved(tmp_path, monkeypatch):
    remote, seed, checkout = _repositories(tmp_path)
    _add_upstream_commit(seed, "upstream\n")
    (checkout / "tracked.txt").write_text("local work\n", encoding="utf-8")
    original_head = _git(checkout, "rev-parse", "HEAD")

    monkeypatch.chdir(checkout)
    monkeypatch.setattr(update, "_ALLOWLIST_PATTERNS", [re_compile(r".*")])

    assert update._run_update(str(remote), "main", "test") is False
    assert (checkout / "tracked.txt").read_text(encoding="utf-8") == "local work\n"
    assert _git(checkout, "rev-parse", "HEAD") == original_head
    assert _git(checkout, "status", "--porcelain") == "M tracked.txt"
    _git(checkout, "fetch", "origin")


def test_clean_working_tree_fast_forwards(tmp_path, monkeypatch):
    remote, seed, checkout = _repositories(tmp_path)
    _add_upstream_commit(seed, "upstream\n")
    expected_head = _git(seed, "rev-parse", "HEAD")

    monkeypatch.chdir(checkout)
    monkeypatch.setattr(update, "_ALLOWLIST_PATTERNS", [re_compile(r".*")])

    assert update._run_update(str(remote), "main", "test") is True
    assert _git(checkout, "rev-parse", "HEAD") == expected_head
    assert (checkout / "tracked.txt").read_text(encoding="utf-8") == "upstream\n"
    _git(checkout, "fetch", "origin")
    _git(checkout, "pull", "--ff-only")


def test_clean_local_commits_are_not_rewritten(tmp_path, monkeypatch):
    remote, _, checkout = _repositories(tmp_path)
    _git(checkout, "config", "user.email", "tests@example.invalid")
    _git(checkout, "config", "user.name", "Amaterasu tests")
    (checkout / "tracked.txt").write_text("local commit\n", encoding="utf-8")
    _git(checkout, "add", "tracked.txt")
    _git(checkout, "commit", "-m", "local work")
    local_head = _git(checkout, "rev-parse", "HEAD")

    monkeypatch.chdir(checkout)
    monkeypatch.setattr(update, "_ALLOWLIST_PATTERNS", [re_compile(r".*")])

    assert update._run_update(str(remote), "main", "test") is False
    assert _git(checkout, "rev-parse", "HEAD") == local_head
    assert (checkout / "tracked.txt").read_text(encoding="utf-8") == "local commit\n"


def test_detached_head_is_left_unchanged(tmp_path, monkeypatch):
    remote, _, checkout = _repositories(tmp_path)
    detached_head = _git(checkout, "rev-parse", "HEAD")
    _git(checkout, "checkout", "--detach", detached_head)

    monkeypatch.chdir(checkout)
    monkeypatch.setattr(update, "_ALLOWLIST_PATTERNS", [re_compile(r".*")])

    assert update._run_update(str(remote), "main", "test") is False
    assert _git(checkout, "rev-parse", "HEAD") == detached_head


def test_auto_update_false_never_calls_git_updater(monkeypatch):
    calls = []
    monkeypatch.setattr(update, "_setup_logging", lambda: None)
    monkeypatch.setattr(update, "_get_version", lambda: "test")
    monkeypatch.setattr(
        update,
        "_load_config",
        lambda: {
            "BOT_TOKEN": "123:token",
            "AUTO_UPDATE": False,
            "UPSTREAM_REPO": "https://github.com/example/Amaterasu",
            "UPSTREAM_BRANCH": "main",
            "UPDATE_PKGS": False,
        },
    )
    monkeypatch.setattr(update, "_fetch_config_from_db", lambda *_: None)
    monkeypatch.setattr(update, "_run_update", lambda *_: calls.append("git"))
    monkeypatch.setattr(update, "_update_packages", lambda *_: None)
    for key in update._VAR_LIST:
        monkeypatch.delenv(key, raising=False)

    update.main()

    assert calls == []


def test_saved_auto_update_true_reaches_every_restart_entry_point(monkeypatch):
    calls = []
    monkeypatch.setattr(update, "_setup_logging", lambda: None)
    monkeypatch.setattr(update, "_get_version", lambda: "test")
    monkeypatch.setattr(
        update,
        "_load_config",
        lambda: {
            "BOT_TOKEN": "123:token",
            "AUTO_UPDATE": False,
            "UPSTREAM_REPO": "https://github.com/example/Amaterasu",
            "UPSTREAM_BRANCH": "main",
            "UPDATE_PKGS": False,
        },
    )

    def load_saved_config(config_file, _):
        config_file["AUTO_UPDATE"] = True

    monkeypatch.setattr(update, "_fetch_config_from_db", load_saved_config)
    monkeypatch.setattr(update, "_run_update", lambda *_: calls.append("git"))
    monkeypatch.setattr(update, "_update_packages", lambda *_: None)
    for key in update._VAR_LIST:
        monkeypatch.delenv(key, raising=False)

    update.main()

    assert calls == ["git"]


def test_explicit_false_environment_overrides_saved_true(monkeypatch):
    calls = []
    monkeypatch.setattr(update, "_setup_logging", lambda: None)
    monkeypatch.setattr(update, "_get_version", lambda: "test")
    monkeypatch.setattr(
        update,
        "_load_config",
        lambda: {
            "BOT_TOKEN": "123:token",
            "UPSTREAM_REPO": "https://github.com/example/Amaterasu",
            "UPSTREAM_BRANCH": "main",
            "UPDATE_PKGS": False,
        },
    )

    def load_saved_config(config_file, _):
        config_file["AUTO_UPDATE"] = True

    monkeypatch.setattr(update, "_fetch_config_from_db", load_saved_config)
    monkeypatch.setattr(update, "_run_update", lambda *_: calls.append("git"))
    monkeypatch.setattr(update, "_update_packages", lambda *_: None)
    for key in update._VAR_LIST:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AUTO_UPDATE", "false")

    update.main()

    assert calls == []


def test_compose_only_passes_auto_update_when_explicitly_configured():
    for filename in ("docker-compose.yml", "docker-compose.dev.yml"):
        compose = (ROOT / filename).read_text(encoding="utf-8")
        assert "- AUTO_UPDATE\n" in compose
        assert "AUTO_UPDATE=${AUTO_UPDATE:-false}" not in compose


def test_updater_contains_no_destructive_git_commands():
    source = Path(update.__file__).read_text(encoding="utf-8")
    assert '"reset", "--hard"' not in source
    assert '"clean", "-fd"' not in source
    assert 'rmtree(".git"' not in source


def _load_runtime_paths(monkeypatch, runtime_dir):
    monkeypatch.setenv("AMATERASU_RUNTIME_DIR", str(runtime_dir))
    module_path = ROOT / "bot/core/runtime_paths.py"
    spec = spec_from_file_location("runtime_paths_under_test", module_path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_engine_runtime_configs_are_outside_checkout_and_preserved(
    tmp_path, monkeypatch
):
    runtime_dir = tmp_path / "runtime"
    runtime_paths = _load_runtime_paths(monkeypatch, runtime_dir)

    config_path = runtime_paths.ensure_sabnzbd_runtime_config()
    assert config_path == runtime_dir / "sabnzbd/SABnzbd.ini"
    assert config_path.read_bytes() == runtime_paths.SABNZBD_TEMPLATE_PATH.read_bytes()

    config_path.write_text("operator runtime configuration\n", encoding="utf-8")
    runtime_paths.ensure_sabnzbd_runtime_config()
    assert config_path.read_text(encoding="utf-8") == (
        "operator runtime configuration\n"
    )

    qbit_profile = runtime_paths.ensure_qbittorrent_runtime_profile()
    qbit_config = qbit_profile / "qBittorrent/config/qBittorrent.conf"
    assert qbit_profile == runtime_dir / "qbittorrent"
    assert qbit_config.read_bytes() == (
        runtime_paths.QBITTORRENT_TEMPLATE_PATH.read_bytes()
    )

    qbit_config.write_text("operator qBittorrent configuration\n", encoding="utf-8")
    runtime_paths.ensure_qbittorrent_runtime_profile()
    assert qbit_config.read_text(encoding="utf-8") == (
        "operator qBittorrent configuration\n"
    )


def test_startup_does_not_modify_tracked_sabnzbd_or_script_files():
    startup = (ROOT / "bot/core/startup.py").read_text(encoding="utf-8")
    db_handler = (ROOT / "bot/helper/ext_utils/db_handler.py").read_text(
        encoding="utf-8"
    )
    bot_init = (ROOT / "bot/__init__.py").read_text(encoding="utf-8")
    setpkgs = (ROOT / "setpkgs.sh").read_text(encoding="utf-8")
    torrent_manager = (ROOT / "bot/core/torrent_manager.py").read_text(
        encoding="utf-8"
    )

    assert "chmod +x setpkgs.sh" not in startup
    assert 'create_subprocess_exec(*setpkgs_args)' in startup
    assert 'configs/sabnzbd/SABnzbd.ini", "rb+"' not in startup
    assert 'configs/sabnzbd/SABnzbd.ini", "rb+"' not in db_handler
    assert 'open("configs/sabnzbd/SABnzbd.ini"' not in bot_init
    assert '-f "$SABNZBD_CONFIG"' in setpkgs
    assert "getcwd()}/configs/qbittorrent" not in torrent_manager
    assert "ensure_qbittorrent_runtime_profile" in torrent_manager


def test_runtime_artifacts_are_git_ignored():
    generated_paths = (
        ".runtime/sabnzbd/SABnzbd.ini",
        ".restartmsg",
        ".restartmsg.tmp",
        "latestversion.py",
        "rclone_sa/remote.conf",
        "rclone_select_deadbeef.txt",
        "terabox.txt",
        "terabox_cookies/123.txt",
        "configs/sabnzbd/logs/sabnzbd.log",
        "configs/qbittorrent/qBittorrent/cache/runtime",
        "configs/qbittorrent/qBittorrent/data/logs/qbittorrent.log",
        "configs/qbittorrent/qBittorrent/GeoDB/GeoLite2-Country.mmdb",
    )
    for path in generated_paths:
        assert _git(ROOT, "check-ignore", path) == path
